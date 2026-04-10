from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
import secrets
from typing import Any
import uuid

from runtime.errors import SessionAuthError
from runtime.assistant_grounding import build_assistant_prompt_context
from runtime.memory import list_memories, memory_summary
from runtime.state import load_state_payload, write_state_payload
from runtime.workflow_runner import start_workflow


BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_DIR = BASE_DIR / "sessions"
SESSION_STATE_SCHEMA = "session.v1"
DEFAULT_SESSION_AUTH_HEADER = "X-Session-Token"

SESSION_STATUSES = {"open", "active", "waiting", "errored", "archived", "recovered"}
SESSION_STATUS_TRANSITIONS = {
    "open": {"active", "waiting", "errored", "archived"},
    "active": {"active", "waiting", "errored", "archived"},
    "waiting": {"active", "waiting", "errored", "recovered", "archived"},
    "errored": {"active", "waiting", "recovered", "archived"},
    "recovered": {"active", "waiting", "errored", "archived"},
    "archived": set(),
}
SESSION_MESSAGE_ROLES = {"user", "assistant", "system"}
SESSION_MESSAGE_STATUSES = {"submitted", "completed", "waiting", "errored"}
SESSION_SCOPE_KINDS = {"global", "agent", "workflow", "run"}
CONTINUITY_COMPACTION_STRATEGY = "session_compaction_v1"
MAX_STORED_COMPACTIONS = 5
CONTINUITY_KEEP_RECENT_MESSAGES = 6
CONTINUITY_RECENT_MESSAGE_LIMIT = 4
CONTINUITY_SOURCE_MEMORY_LIMIT = 4
CONTINUITY_MAX_SUMMARY_CHARS = 900
CONTINUITY_MAX_UNCOMPACTED_MESSAGES = 8
CONTINUITY_MAX_MESSAGES_BEFORE_COMPACTION = 12


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str, *, field_name: str) -> datetime:
    try:
        return datetime.fromisoformat(normalize_non_empty_string(value, field_name=field_name))
    except ValueError as exc:
        raise ValueError(f"Session `{field_name}` must be an ISO 8601 timestamp") from exc


def ensure_session_dir() -> None:
    SESSION_DIR.mkdir(exist_ok=True)


def session_path(session_id: str) -> Path:
    return SESSION_DIR / f"{session_id}.json"


def normalize_non_empty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Session `{field_name}` must be a non-empty string")
    return value.strip()


def normalize_optional_string(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return normalize_non_empty_string(value, field_name=field_name)


def normalize_optional_message_content(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Session message `content` must be a string when provided")
    stripped = value.strip()
    return stripped or None


def normalize_metadata(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Session `metadata` must be an object")
    return dict(value)


def normalize_status(status: str) -> str:
    if status not in SESSION_STATUSES:
        raise ValueError(f"Unknown session status: {status}")
    return status


def normalize_message_role(role: str) -> str:
    if role not in SESSION_MESSAGE_ROLES:
        raise ValueError(f"Unknown session message role: {role}")
    return role


def normalize_message_status(status: str) -> str:
    if status not in SESSION_MESSAGE_STATUSES:
        raise ValueError(f"Unknown session message status: {status}")
    return status


def normalize_transition_history(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Session `transition_history` must be a list")

    normalized = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("Session `transition_history` entries must be objects")
        normalized.append(dict(entry))
    return normalized


def normalize_positive_int(value: object, *, field_name: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"Session `{field_name}` must be a positive integer")
    return value


def normalize_scope_value(scope_kind: str, value: object) -> str | None:
    if scope_kind == "global":
        return None
    return normalize_non_empty_string(value, field_name="memory_scope.value")


def normalize_memory_scope(memory_scope: object, *, agent: str) -> dict[str, str | None]:
    if memory_scope is None:
        return {
            "kind": "agent",
            "value": agent,
        }
    if not isinstance(memory_scope, dict):
        raise ValueError("Session `memory_scope` must be an object")

    kind = memory_scope.get("kind", "agent")
    if kind not in SESSION_SCOPE_KINDS:
        raise ValueError(f"Unknown session memory scope kind: {kind}")
    value = normalize_scope_value(kind, memory_scope.get("value", agent if kind == "agent" else None))
    return {
        "kind": kind,
        "value": value,
    }


def normalize_ownership(value: object) -> dict[str, Any]:
    if value is None:
        return {
            "auth_required": False,
            "surface": None,
            "token_hash": None,
            "issued_at": None,
        }
    if not isinstance(value, dict):
        raise ValueError("Session `ownership` must be an object")

    auth_required = value.get("auth_required", False)
    if not isinstance(auth_required, bool):
        raise ValueError("Session `ownership.auth_required` must be a boolean")

    token_hash = normalize_optional_string(value.get("token_hash"), field_name="ownership.token_hash")
    if auth_required and token_hash is None:
        raise ValueError("Owned sessions must persist `ownership.token_hash`")

    return {
        "auth_required": auth_required,
        "surface": normalize_optional_string(value.get("surface"), field_name="ownership.surface"),
        "token_hash": token_hash,
        "issued_at": normalize_optional_string(value.get("issued_at"), field_name="ownership.issued_at"),
    }


def session_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_session_token() -> str:
    return secrets.token_urlsafe(24)


def public_ownership_snapshot(ownership: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_ownership(ownership)
    return {
        "auth_required": normalized["auth_required"],
        "surface": normalized["surface"],
        "issued_at": normalized["issued_at"],
    }


def storage_ownership_snapshot(ownership: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_ownership(ownership)
    return {
        "auth_required": normalized["auth_required"],
        "surface": normalized["surface"],
        "token_hash": normalized["token_hash"],
        "issued_at": normalized["issued_at"],
    }


def session_auth_required(session) -> bool:
    return bool(session.ownership.get("auth_required"))


def verify_session_access(
    session,
    session_token: str | None,
    *,
    header_name: str = DEFAULT_SESSION_AUTH_HEADER,
) -> None:
    if not session_auth_required(session):
        return

    expected_hash = normalize_optional_string(
        session.ownership.get("token_hash"),
        field_name="ownership.token_hash",
    )
    candidate = session_token.strip() if isinstance(session_token, str) else ""
    if not expected_hash or not candidate:
        raise SessionAuthError(
            f"Session token is required via `{header_name}`",
            header_name=header_name,
            session_id=session.session_id,
        )
    if not hmac.compare_digest(session_token_hash(candidate), expected_hash):
        raise SessionAuthError(
            f"Valid session token is required via `{header_name}`",
            header_name=header_name,
            session_id=session.session_id,
        )


def default_title(content: str) -> str:
    stripped = content.strip()
    if len(stripped) <= 60:
        return stripped
    return stripped[:57].rstrip() + "..."


def follow_memory_scope(
    session,
    *,
    workflow_id: str | None,
    run_id: str | None,
) -> None:
    scope_kind = session.memory_scope["kind"]
    if scope_kind == "workflow":
        session.memory_scope["value"] = normalize_optional_string(workflow_id, field_name="memory_scope.value")
    elif scope_kind == "run":
        session.memory_scope["value"] = normalize_optional_string(run_id, field_name="memory_scope.value")


def transition_entry(event_type: str, timestamp: str, **details: Any) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "timestamp": timestamp,
        **details,
    }


def unique_strings(values: list[str | None]) -> list[str]:
    normalized = []
    seen = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        item = value.strip()
        if item in seen:
            continue
        normalized.append(item)
        seen.add(item)
    return normalized


def truncate_text(value: str | None, *, limit: int = 120) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def message_preview_for_summary(message, *, limit: int = 96) -> str:
    content = normalize_optional_message_content(message.content)
    if content is None:
        content = f"[{message.status}]"
    preview = truncate_text(content, limit=limit) or f"[{message.status}]"
    label = message.role
    if message.status != "completed":
        label = f"{label} ({message.status})"
    return f"- {label}: {preview}"


def summarize_message_window(messages: list, *, max_chars: int) -> str:
    if not messages:
        return "No messages were selected for continuity compaction."

    role_counts = {
        "user": 0,
        "assistant": 0,
        "system": 0,
    }
    for message in messages:
        role_counts[message.role] = role_counts.get(message.role, 0) + 1

    lines = [
        (
            f"Compacted {len(messages)} earlier messages spanning "
            f"{messages[0].created_at} to {messages[-1].created_at}. "
            f"Roles: user={role_counts['user']}, assistant={role_counts['assistant']}, system={role_counts['system']}."
        )
    ]
    for message in messages:
        lines.append(message_preview_for_summary(message))

    summary = []
    used = 0
    for line in lines:
        candidate = line if not summary else f"\n{line}"
        if used + len(candidate) > max_chars:
            if not summary:
                return truncate_text(line, limit=max_chars) or line[:max_chars]
            summary.append("\n...")
            break
        summary.append(candidate)
        used += len(candidate)
    return "".join(summary)


def continuity_scope_memories(session, *, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scope = dict(session.memory_scope)
    scope_kind = scope["kind"]
    scope_value = scope.get("value")

    if scope_kind == "global":
        scoped = list_memories(scope_kind="global", limit=limit)
    elif scope_kind == "agent":
        scoped = list_memories(scope_kind="agent", agent=scope_value, limit=limit)
    elif scope_kind == "workflow":
        scoped = list_memories(scope_kind="workflow", workflow_id=scope_value, limit=limit) if scope_value else []
    else:
        scoped = list_memories(scope_kind="run", run_id=scope_value, limit=limit) if scope_value else []

    recent = [memory_summary(memory) for memory in scoped]

    workflow_memories = []
    seen = set()
    for workflow_id in session.workflow_ids:
        for memory in list_memories(scope_kind="workflow", workflow_id=workflow_id, limit=limit):
            memory_id = memory["memory_id"]
            if memory_id in seen:
                continue
            workflow_memories.append(memory_summary(memory))
            seen.add(memory_id)
            if len(workflow_memories) >= limit:
                break
        if len(workflow_memories) >= limit:
            break

    return recent, workflow_memories


def continuity_metadata(session) -> dict[str, Any]:
    metadata = session.metadata if isinstance(session.metadata, dict) else {}
    continuity = metadata.get("continuity")
    if not isinstance(continuity, dict):
        return {
            "compactions": [],
            "active_compaction_id": None,
            "active_compaction": None,
            "active_summary": None,
            "updated_at": None,
        }

    compactions = [dict(entry) for entry in continuity.get("compactions", []) if isinstance(entry, dict)]
    active_compaction_id = continuity.get("active_compaction_id")
    active_compaction = None
    for entry in compactions:
        if entry.get("compaction_id") == active_compaction_id:
            active_compaction = dict(entry)
            break
    if active_compaction is None and compactions:
        active_compaction = dict(compactions[0])
        active_compaction_id = active_compaction.get("compaction_id")

    return {
        "compactions": compactions,
        "active_compaction_id": active_compaction_id,
        "active_compaction": active_compaction,
        "active_summary": dict(continuity.get("active_summary")) if isinstance(continuity.get("active_summary"), dict) else None,
        "updated_at": normalize_optional_string(continuity.get("updated_at"), field_name="metadata.continuity.updated_at"),
    }


def session_continuity_snapshot(session) -> dict[str, Any]:
    continuity = continuity_metadata(session)
    return {
        "compaction_count": len(continuity["compactions"]),
        "active_compaction_id": continuity["active_compaction_id"],
        "active_compaction": dict(continuity["active_compaction"]) if continuity["active_compaction"] is not None else None,
        "active_summary": dict(continuity["active_summary"]) if continuity.get("active_summary") is not None else None,
        "updated_at": continuity["updated_at"],
    }


def continuity_budget_limits() -> dict[str, int]:
    return {
        "keep_recent_messages": CONTINUITY_KEEP_RECENT_MESSAGES,
        "recent_message_limit": CONTINUITY_RECENT_MESSAGE_LIMIT,
        "source_memory_limit": CONTINUITY_SOURCE_MEMORY_LIMIT,
        "max_summary_chars": CONTINUITY_MAX_SUMMARY_CHARS,
        "max_uncompacted_messages": CONTINUITY_MAX_UNCOMPACTED_MESSAGES,
        "max_messages_before_compaction": CONTINUITY_MAX_MESSAGES_BEFORE_COMPACTION,
    }


def session_continuity_budget(session) -> dict[str, Any]:
    limits = continuity_budget_limits()
    continuity = continuity_metadata(session)
    active_compaction = continuity["active_compaction"]
    active_summary = continuity["active_summary"]

    if active_compaction is None:
        uncompacted_messages = list(session.messages)
        new_messages_since_compaction = list(session.messages)
    else:
        compacted_ids = set(active_compaction.get("compacted_message_ids", []))
        retained_ids = set(active_compaction.get("retained_message_ids", []))
        uncompacted_messages = [
            message for message in session.messages if message.message_id not in compacted_ids
        ]
        new_messages_since_compaction = [
            message
            for message in session.messages
            if message.message_id not in compacted_ids and message.message_id not in retained_ids
        ]

    carry_forward = active_summary.get("carry_forward", {}) if isinstance(active_summary, dict) else {}
    recent_message_count = int(carry_forward.get("recent_message_count", 0) or 0)
    source_memory_count = int(carry_forward.get("source_memory_count", 0) or 0)
    source_workflow_count = len(carry_forward.get("source_workflow_ids", []))
    summary_chars = len(active_summary.get("summary", "")) if isinstance(active_summary, dict) else 0

    recommendation = "within_budget"
    if active_compaction is None and len(session.messages) > limits["max_messages_before_compaction"]:
        recommendation = "compact_now"
    elif active_compaction is not None and len(uncompacted_messages) > limits["max_uncompacted_messages"]:
        recommendation = "recompact_now"
    elif active_summary is None and active_compaction is not None:
        recommendation = "refresh_summary"
    elif (
        recent_message_count >= limits["recent_message_limit"]
        or source_memory_count >= limits["source_memory_limit"]
        or summary_chars >= limits["max_summary_chars"]
    ):
        recommendation = "monitor_budget"

    return {
        "limits": limits,
        "counts": {
            "total_messages": len(session.messages),
            "uncompacted_messages": len(uncompacted_messages),
            "new_messages_since_compaction": len(new_messages_since_compaction),
            "carry_forward_recent_messages": recent_message_count,
            "carry_forward_source_memories": source_memory_count,
            "carry_forward_source_workflows": source_workflow_count,
            "carry_forward_summary_chars": summary_chars,
        },
        "active": {
            "has_compaction": active_compaction is not None,
            "has_summary": active_summary is not None,
        },
        "status": {
            "needs_initial_compaction": recommendation == "compact_now",
            "needs_recompaction": recommendation == "recompact_now",
            "summary_missing": recommendation == "refresh_summary",
            "at_or_near_budget": recommendation == "monitor_budget",
        },
        "recommendation": recommendation,
    }


def bounded_lines_text(lines: list[str], *, max_chars: int) -> str:
    if not lines:
        return ""

    blocks = []
    used = 0
    for line in lines:
        candidate = line if not blocks else f"\n{line}"
        if used + len(candidate) > max_chars:
            if not blocks:
                return truncate_text(line, limit=max_chars) or line[:max_chars]
            blocks.append("\n...")
            break
        blocks.append(candidate)
        used += len(candidate)
    return "".join(blocks)


def format_memory_scope(scope: dict[str, str | None]) -> str:
    scope_kind = scope.get("kind", "unknown")
    scope_value = scope.get("value")
    if scope_value:
        return f"{scope_kind}:{scope_value}"
    return scope_kind


def select_continuity_memories(session, *, limit: int) -> list[dict[str, Any]]:
    recent_memories, workflow_memories = continuity_scope_memories(session, limit=limit)
    selected = []
    seen = set()
    for memory in [*recent_memories, *workflow_memories]:
        memory_id = memory.get("memory_id")
        if not isinstance(memory_id, str) or not memory_id.strip() or memory_id in seen:
            continue
        selected.append(memory)
        seen.add(memory_id)
        if len(selected) >= limit:
            break
    return selected


def build_session_continuity_summary(
    session,
    *,
    exclude_message_ids: set[str] | None = None,
    recent_message_limit: int = CONTINUITY_RECENT_MESSAGE_LIMIT,
    memory_limit: int = CONTINUITY_SOURCE_MEMORY_LIMIT,
    max_chars: int = CONTINUITY_MAX_SUMMARY_CHARS,
) -> dict[str, Any] | None:
    continuity = continuity_metadata(session)
    active_compaction = continuity["active_compaction"]
    if active_compaction is None:
        return None

    exclude_message_ids = exclude_message_ids or set()
    recent_message_limit = max(recent_message_limit, 1)
    memory_limit = max(memory_limit, 1)
    max_chars = max(max_chars, 240)

    recent_messages = [
        message
        for message in session.messages
        if message.message_id not in exclude_message_ids
    ][-recent_message_limit:]
    selected_memories = select_continuity_memories(session, limit=memory_limit)
    source_memory_ids = [memory["memory_id"] for memory in selected_memories]
    source_workflow_ids = unique_strings(
        [
            session.current_workflow_id,
            *active_compaction.get("source_workflow_ids", []),
            *[message.workflow_id for message in recent_messages],
            *[memory.get("workflow_id") for memory in selected_memories],
        ]
    )
    lines = [
        "Carry-forward summary for this session.",
        (
            f"Session status: {session.status}. "
            f"Current workflow: {session.current_workflow_id or 'none'}. "
            f"Memory scope: {format_memory_scope(session.memory_scope)}."
        ),
    ]

    earlier_summary = truncate_text(active_compaction.get("summary"), limit=min(max_chars // 2, 480))
    if earlier_summary:
        lines.append("Earlier compacted context:")
        lines.append(earlier_summary)

    if recent_messages:
        lines.append("Recent message tail:")
        for message in recent_messages:
            lines.append(message_preview_for_summary(message, limit=84))

    if selected_memories:
        lines.append("Relevant continuity memories:")
        for memory in selected_memories:
            lines.append(
                f"- [{memory['memory_id']}] "
                f"{truncate_text(memory.get('payload_summary'), limit=92) or 'memory'}"
            )

    return {
        "kind": "session_continuity_summary",
        "based_on_compaction_id": active_compaction.get("compaction_id"),
        "updated_at": utc_now(),
        "summary": bounded_lines_text(lines, max_chars=max_chars),
        "carry_forward": {
            "limits": {
                "recent_message_limit": recent_message_limit,
                "source_memory_limit": memory_limit,
                "max_summary_chars": max_chars,
            },
            "session_status": session.status,
            "current_workflow_id": session.current_workflow_id,
            "memory_scope": dict(session.memory_scope),
            "recent_message_ids": [message.message_id for message in recent_messages],
            "source_memory_ids": source_memory_ids,
            "source_workflow_ids": source_workflow_ids,
            "recent_message_count": len(recent_messages),
            "source_memory_count": len(selected_memories),
        },
    }


def refresh_session_continuity_summary(
    session,
    *,
    recent_message_limit: int = CONTINUITY_RECENT_MESSAGE_LIMIT,
    memory_limit: int = CONTINUITY_SOURCE_MEMORY_LIMIT,
    max_chars: int = CONTINUITY_MAX_SUMMARY_CHARS,
) -> dict[str, Any] | None:
    continuity = continuity_metadata(session)
    state = {
        "compactions": [dict(entry) for entry in continuity["compactions"]],
        "active_compaction_id": continuity["active_compaction_id"],
        "updated_at": continuity["updated_at"],
    }
    summary = build_session_continuity_summary(
        session,
        recent_message_limit=recent_message_limit,
        memory_limit=memory_limit,
        max_chars=max_chars,
    )
    if summary is not None:
        state["active_summary"] = summary
        state["updated_at"] = summary["updated_at"]
    session.metadata["continuity"] = state
    return summary


def build_session_continuity_prompt_context(
    session,
    *,
    exclude_message_ids: set[str] | None = None,
    recent_message_limit: int = CONTINUITY_RECENT_MESSAGE_LIMIT,
    memory_limit: int = CONTINUITY_SOURCE_MEMORY_LIMIT,
    max_chars: int = CONTINUITY_MAX_SUMMARY_CHARS,
) -> list[dict[str, str]]:
    summary = build_session_continuity_summary(
        session,
        exclude_message_ids=exclude_message_ids,
        recent_message_limit=recent_message_limit,
        memory_limit=memory_limit,
        max_chars=max_chars,
    )
    if summary is None:
        return []
    return [
        {
            "title": "Session continuity",
            "source": f"session_continuity:{session.session_id}",
            "content": summary["summary"],
        }
    ]


def session_target_status(previous_status: str, workflow_status: str) -> str:
    if workflow_status == "success":
        if previous_status in {"waiting", "errored"}:
            return "recovered"
        return "active"
    if workflow_status in {"pending", "retry_wait"}:
        return "waiting"
    return "errored"


def session_terminal_for_cleanup(session) -> bool:
    return session.status in {"archived", "errored", "recovered"}


def transition_session(session, next_status: str) -> None:
    normalize_status(session.status)
    normalize_status(next_status)
    if next_status not in SESSION_STATUS_TRANSITIONS[session.status]:
        raise ValueError(
            f"Cannot transition session `{session.session_id}` from `{session.status}` to `{next_status}`"
        )
    session.status = next_status


def build_session_transition_history(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> list[dict[str, Any]]:
    history = normalize_transition_history(
        previous.get("transition_history") if previous is not None else current.get("transition_history")
    )
    timestamp = current["updated_at"]

    if previous is None:
        history.append(
            transition_entry(
                "created",
                timestamp,
                status=current["status"],
                agent=current["agent"],
                memory_scope=dict(current["memory_scope"]),
            )
        )
        return history

    if previous.get("status") != current["status"]:
        history.append(
            transition_entry(
                "session_status_changed",
                timestamp,
                from_status=previous.get("status"),
                to_status=current["status"],
            )
        )

    if previous.get("current_workflow_id") != current.get("current_workflow_id"):
        history.append(
            transition_entry(
                "current_workflow_changed",
                timestamp,
                from_workflow_id=previous.get("current_workflow_id"),
                to_workflow_id=current.get("current_workflow_id"),
            )
        )

    if previous.get("last_run_id") != current.get("last_run_id"):
        history.append(
            transition_entry(
                "last_run_changed",
                timestamp,
                from_run_id=previous.get("last_run_id"),
                to_run_id=current.get("last_run_id"),
            )
        )

    previous_continuity = (((previous or {}).get("metadata") or {}).get("continuity") or {}) if previous is not None else {}
    current_continuity = (((current or {}).get("metadata") or {}).get("continuity") or {})
    previous_compaction_id = previous_continuity.get("active_compaction_id")
    current_compaction_id = current_continuity.get("active_compaction_id")
    if current_compaction_id != previous_compaction_id:
        current_compactions = current_continuity.get("compactions", [])
        active_compaction = next(
            (
                entry
                for entry in current_compactions
                if isinstance(entry, dict) and entry.get("compaction_id") == current_compaction_id
            ),
            None,
        )
        if isinstance(active_compaction, dict):
            history.append(
                transition_entry(
                    "continuity_compacted",
                    timestamp,
                    compaction_id=current_compaction_id,
                    strategy=active_compaction.get("strategy"),
                    compacted_message_count=active_compaction.get("message_count"),
                    retained_message_count=len(active_compaction.get("retained_message_ids", [])),
                    source_memory_count=len(active_compaction.get("source_memory_ids", [])),
                )
            )

    previous_ids = {
        message.get("message_id")
        for message in previous.get("messages", [])
        if isinstance(message, dict)
    }
    for message in current.get("messages", []):
        if not isinstance(message, dict):
            continue
        message_id = message.get("message_id")
        if message_id in previous_ids:
            continue
        history.append(
            transition_entry(
                "message_appended",
                timestamp,
                message_id=message_id,
                role=message.get("role"),
                status=message.get("status"),
                workflow_id=message.get("workflow_id"),
                run_id=message.get("run_id"),
            )
        )

    return history


@dataclass
class SessionMessage:
    message_id: str
    role: str
    content: str | None
    status: str
    created_at: str
    agent: str | None = None
    workflow_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    worker_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionRecord:
    session_id: str
    title: str | None
    agent: str
    status: str
    ownership: dict[str, Any]
    memory_scope: dict[str, str | None]
    current_workflow_id: str | None
    workflow_ids: list[str]
    last_run_id: str | None
    last_job_id: str | None
    messages: list[SessionMessage]
    metadata: dict[str, Any]
    transition_history: list[dict[str, Any]]
    created_at: str
    updated_at: str


def message_snapshot(message: SessionMessage) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "role": message.role,
        "content": message.content,
        "status": message.status,
        "created_at": message.created_at,
        "agent": message.agent,
        "workflow_id": message.workflow_id,
        "run_id": message.run_id,
        "job_id": message.job_id,
        "worker_id": message.worker_id,
        "metadata": dict(message.metadata),
    }


def session_summary(session: SessionRecord) -> dict[str, Any]:
    last_message = session.messages[-1] if session.messages else None
    return {
        "session_id": session.session_id,
        "title": session.title,
        "agent": session.agent,
        "status": session.status,
        "ownership": public_ownership_snapshot(session.ownership),
        "memory_scope": dict(session.memory_scope),
        "current_workflow_id": session.current_workflow_id,
        "workflow_ids": list(session.workflow_ids),
        "last_run_id": session.last_run_id,
        "last_job_id": session.last_job_id,
        "message_count": len(session.messages),
        "last_message": message_snapshot(last_message) if last_message is not None else None,
        "metadata": dict(session.metadata),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def session_snapshot(session: SessionRecord) -> dict[str, Any]:
    return {
        **session_summary(session),
        "messages": [message_snapshot(message) for message in session.messages],
        "transition_history": [dict(entry) for entry in session.transition_history],
    }


def session_storage_payload(session: SessionRecord) -> dict[str, Any]:
    return {
        **session_snapshot(session),
        "ownership": storage_ownership_snapshot(session.ownership),
    }


def write_session(session: SessionRecord) -> dict[str, Any]:
    ensure_session_dir()
    session.updated_at = utc_now()
    path = session_path(session.session_id)
    previous = load_state_payload(path, schema=SESSION_STATE_SCHEMA) if path.is_file() else None
    snapshot = session_storage_payload(session)
    session.transition_history = build_session_transition_history(previous, snapshot)
    snapshot["transition_history"] = [dict(entry) for entry in session.transition_history]
    write_state_payload(path, snapshot, schema=SESSION_STATE_SCHEMA)
    return session_snapshot(session)


def load_session(session_id: str) -> SessionRecord:
    path = session_path(session_id)
    if not path.is_file():
        raise FileNotFoundError(f"Session not found: {session_id}")

    data = load_state_payload(path, schema=SESSION_STATE_SCHEMA)
    return SessionRecord(
        session_id=data["session_id"],
        title=normalize_optional_string(data.get("title"), field_name="title"),
        agent=normalize_non_empty_string(data.get("agent", "default"), field_name="agent"),
        status=normalize_status(data.get("status", "open")),
        ownership=normalize_ownership(data.get("ownership")),
        memory_scope=normalize_memory_scope(
            data.get("memory_scope"),
            agent=normalize_non_empty_string(data.get("agent", "default"), field_name="agent"),
        ),
        current_workflow_id=normalize_optional_string(data.get("current_workflow_id"), field_name="current_workflow_id"),
        workflow_ids=unique_strings(data.get("workflow_ids", [])),
        last_run_id=normalize_optional_string(data.get("last_run_id"), field_name="last_run_id"),
        last_job_id=normalize_optional_string(data.get("last_job_id"), field_name="last_job_id"),
        messages=[
            SessionMessage(
                message_id=normalize_non_empty_string(message["message_id"], field_name="messages[].message_id"),
                role=normalize_message_role(message["role"]),
                content=normalize_optional_message_content(message.get("content")),
                status=normalize_message_status(message["status"]),
                created_at=normalize_non_empty_string(message["created_at"], field_name="messages[].created_at"),
                agent=normalize_optional_string(message.get("agent"), field_name="messages[].agent"),
                workflow_id=normalize_optional_string(message.get("workflow_id"), field_name="messages[].workflow_id"),
                run_id=normalize_optional_string(message.get("run_id"), field_name="messages[].run_id"),
                job_id=normalize_optional_string(message.get("job_id"), field_name="messages[].job_id"),
                worker_id=normalize_optional_string(message.get("worker_id"), field_name="messages[].worker_id"),
                metadata=normalize_metadata(message.get("metadata")),
            )
            for message in data.get("messages", [])
        ],
        metadata=normalize_metadata(data.get("metadata")),
        transition_history=normalize_transition_history(data.get("transition_history")),
        created_at=normalize_non_empty_string(data.get("created_at", utc_now()), field_name="created_at"),
        updated_at=normalize_non_empty_string(data.get("updated_at", utc_now()), field_name="updated_at"),
    )


def create_session(
    *,
    title: str | None = None,
    agent: str = "default",
    metadata: dict | None = None,
    memory_scope: dict | None = None,
    surface: str | None = None,
) -> dict[str, Any]:
    normalized_agent = normalize_non_empty_string(agent, field_name="agent")
    issued_at = utc_now()
    token = generate_session_token()
    session = SessionRecord(
        session_id=str(uuid.uuid4()),
        title=normalize_optional_string(title, field_name="title"),
        agent=normalized_agent,
        status="open",
        ownership={
            "auth_required": True,
            "surface": normalize_optional_string(surface, field_name="surface"),
            "token_hash": session_token_hash(token),
            "issued_at": issued_at,
        },
        memory_scope=normalize_memory_scope(memory_scope, agent=normalized_agent),
        current_workflow_id=None,
        workflow_ids=[],
        last_run_id=None,
        last_job_id=None,
        messages=[],
        metadata=normalize_metadata(metadata),
        transition_history=[],
        created_at=issued_at,
        updated_at=issued_at,
    )
    snapshot = write_session(session)
    return {
        **snapshot,
        "session_token": token,
    }


def list_sessions(
    *,
    status: str | None = None,
    agent: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if status is not None:
        status = normalize_status(status)
    if agent is not None:
        agent = normalize_non_empty_string(agent, field_name="agent")
    if limit is not None:
        limit = normalize_positive_int(limit, field_name="limit")
    if not SESSION_DIR.is_dir():
        return []

    sessions = []
    loaded_sessions = []
    for path in sorted(SESSION_DIR.glob("*.json")):
        session = load_session(path.stem)
        if status is not None and session.status != status:
            continue
        if agent is not None and session.agent != agent:
            continue
        loaded_sessions.append(session)

    loaded_sessions.sort(key=lambda session: session.updated_at, reverse=True)
    for session in loaded_sessions:
        sessions.append(session_summary(session))
        if limit is not None and len(sessions) >= limit:
            break
    return sessions


def archive_session(
    session_id: str,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    session = load_session(session_id)
    if session.status == "archived":
        return session_snapshot(session)

    transition_session(session, "archived")
    notes = dict(session.metadata.get("maintenance", {}))
    notes["archived_at"] = utc_now()
    if reason is not None:
        notes["archive_reason"] = normalize_non_empty_string(reason, field_name="reason")
    session.metadata["maintenance"] = notes
    return write_session(session)


def prune_sessions(
    *,
    statuses: list[str] | None = None,
    older_than_hours: int = 168,
    limit: int | None = None,
) -> dict[str, Any]:
    if statuses is None:
        statuses = ["archived"]
    normalized_statuses = [normalize_status(status) for status in statuses]
    if older_than_hours <= 0:
        raise ValueError("Session prune `older_than_hours` must be a positive integer")
    if limit is not None:
        limit = normalize_positive_int(limit, field_name="limit")

    threshold = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    pruned_session_ids = []
    scanned = 0
    for path in sorted(SESSION_DIR.glob("*.json")):
        session = load_session(path.stem)
        scanned += 1
        if session.status not in normalized_statuses:
            continue
        if not session_terminal_for_cleanup(session):
            continue
        updated_at = parse_timestamp(session.updated_at, field_name="updated_at")
        if updated_at > threshold:
            continue
        path.unlink(missing_ok=False)
        pruned_session_ids.append(session.session_id)
        if limit is not None and len(pruned_session_ids) >= limit:
            break

    return {
        "pruned_count": len(pruned_session_ids),
        "pruned_session_ids": pruned_session_ids,
        "statuses": normalized_statuses,
        "older_than_hours": older_than_hours,
        "scanned": scanned,
    }


def compact_session_continuity(
    session_id: str,
    *,
    keep_recent_messages: int = 6,
    memory_limit: int = 10,
    max_summary_chars: int = 1200,
) -> dict[str, Any]:
    keep_recent_messages = normalize_positive_int(keep_recent_messages, field_name="keep_recent_messages")
    memory_limit = normalize_positive_int(memory_limit, field_name="memory_limit")
    max_summary_chars = normalize_positive_int(max_summary_chars, field_name="max_summary_chars")

    session = load_session(session_id)
    continuity = continuity_metadata(session)
    active_compaction = continuity["active_compaction"]

    if len(session.messages) <= keep_recent_messages:
        return {
            "compacted": False,
            "reason": "not_enough_messages",
            "session": session_snapshot(session),
            "continuity": session_continuity_snapshot(session),
            "compaction": dict(active_compaction) if active_compaction is not None else None,
        }

    compacted_messages = session.messages[:-keep_recent_messages]
    retained_messages = session.messages[-keep_recent_messages:]
    recent_memories, workflow_memories = continuity_scope_memories(session, limit=memory_limit)
    source_memory_ids = unique_strings(
        [
            *[memory.get("memory_id") for memory in recent_memories],
            *[memory.get("memory_id") for memory in workflow_memories],
        ]
    )
    source_workflow_ids = unique_strings(
        [
            *[message.workflow_id for message in compacted_messages],
            *[memory.get("workflow_id") for memory in recent_memories],
            *[memory.get("workflow_id") for memory in workflow_memories],
        ]
    )
    compacted_message_ids = [message.message_id for message in compacted_messages]
    retained_message_ids = [message.message_id for message in retained_messages]

    if active_compaction is not None:
        if (
            active_compaction.get("compacted_message_ids", []) == compacted_message_ids
            and active_compaction.get("retained_message_ids", []) == retained_message_ids
            and active_compaction.get("source_memory_ids", []) == source_memory_ids
        ):
            return {
                "compacted": False,
                "reason": "already_compacted",
                "session": session_snapshot(session),
                "continuity": session_continuity_snapshot(session),
                "compaction": dict(active_compaction),
            }

    timestamp = utc_now()
    role_counts = {
        "user": 0,
        "assistant": 0,
        "system": 0,
    }
    for message in compacted_messages:
        role_counts[message.role] = role_counts.get(message.role, 0) + 1

    compaction = {
        "compaction_id": str(uuid.uuid4()),
        "kind": "session_message_compaction",
        "strategy": CONTINUITY_COMPACTION_STRATEGY,
        "created_at": timestamp,
        "summary": summarize_message_window(compacted_messages, max_chars=max_summary_chars),
        "message_count": len(compacted_messages),
        "message_roles": role_counts,
        "compacted_message_ids": compacted_message_ids,
        "retained_message_ids": retained_message_ids,
        "source_memory_ids": source_memory_ids,
        "source_workflow_ids": source_workflow_ids,
        "memory_scope": dict(session.memory_scope),
        "from_timestamp": compacted_messages[0].created_at,
        "to_timestamp": compacted_messages[-1].created_at,
    }

    prior_compactions = [entry for entry in continuity["compactions"] if isinstance(entry, dict)]
    session.metadata["continuity"] = {
        "compactions": [compaction, *prior_compactions][:MAX_STORED_COMPACTIONS],
        "active_compaction_id": compaction["compaction_id"],
        "updated_at": timestamp,
    }
    refresh_session_continuity_summary(session)
    snapshot = write_session(session)

    return {
        "compacted": True,
        "reason": "compacted",
        "session": snapshot,
        "continuity": session_continuity_snapshot(session),
        "compaction": compaction,
    }


def append_session_message(
    session_id: str,
    *,
    content: str,
    agent: str | None = None,
    tool_name: str | None = None,
    tool_args: dict | None = None,
    approval_id: str | None = None,
    metadata: dict | None = None,
) -> dict[str, Any]:
    session = load_session(session_id)
    if session.status == "archived":
        raise ValueError(f"Session `{session_id}` is archived and cannot accept new messages")

    normalized_content = normalize_non_empty_string(content, field_name="content")
    message_agent = normalize_non_empty_string(agent or session.agent, field_name="agent")
    timestamp = utc_now()
    user_message = SessionMessage(
        message_id=str(uuid.uuid4()),
        role="user",
        content=normalized_content,
        status="submitted",
        created_at=timestamp,
        agent=message_agent,
        metadata={
            **normalize_metadata(metadata),
            "request": {
                "tool": tool_name,
                "tool_args": dict(tool_args or {}) if tool_args is not None else None,
                "approval_id": approval_id,
            },
        },
    )
    session.messages.append(user_message)
    session.agent = message_agent
    session.memory_scope = normalize_memory_scope(session.memory_scope, agent=message_agent)
    if session.title is None:
        session.title = default_title(normalized_content)

    prompt_context = build_session_continuity_prompt_context(
        session,
        exclude_message_ids={user_message.message_id},
    )
    prompt_context.extend(
        build_assistant_prompt_context(
        surface=session.ownership.get("surface"),
        user_input=normalized_content,
        agent_name=message_agent,
        )
    )
    if prompt_context:
        user_message.metadata["grounding"] = {
            "profile": "repo_assistant",
            "sources": [
                {
                    "title": entry.get("title"),
                    "source": entry.get("source"),
                }
                for entry in prompt_context
            ],
        }

    try:
        result = start_workflow(
            user_input=normalized_content,
            agent_name=message_agent,
            tool_name=tool_name,
            tool_args=tool_args,
            approval_id=approval_id,
            prompt_context=prompt_context,
        )
    except Exception as exc:
        transition_session(session, "errored")
        session.messages.append(
            SessionMessage(
                message_id=str(uuid.uuid4()),
                role="assistant",
                content=None,
                status="errored",
                created_at=utc_now(),
                agent=message_agent,
                metadata={
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                },
            )
        )
        write_session(session)
        raise

    workflow = result.get("workflow") or {}
    workflow_id = workflow.get("workflow_id")
    run_id = workflow.get("latest_run_id") or workflow.get("run_id")
    job_id = result.get("job_id")
    worker_id = result.get("worker_id")

    user_message.status = "completed"
    user_message.workflow_id = workflow_id
    user_message.run_id = run_id
    user_message.job_id = job_id
    user_message.worker_id = worker_id

    session.current_workflow_id = normalize_optional_string(workflow_id, field_name="current_workflow_id")
    session.workflow_ids = unique_strings([*session.workflow_ids, workflow_id])
    session.last_run_id = normalize_optional_string(run_id, field_name="last_run_id")
    if isinstance(job_id, str) and job_id.strip():
        session.last_job_id = job_id.strip()
    follow_memory_scope(session, workflow_id=workflow_id, run_id=run_id)

    target_status = session_target_status(session.status, result.get("status", "errored"))
    transition_session(session, target_status)

    assistant_message = SessionMessage(
        message_id=str(uuid.uuid4()),
        role="assistant",
        content=normalize_optional_message_content(result.get("output")),
        status="completed" if result.get("status") == "success" else "waiting",
        created_at=utc_now(),
        agent=message_agent,
        workflow_id=workflow_id,
        run_id=run_id,
        job_id=job_id,
        worker_id=worker_id,
        metadata={
            "result_status": result.get("status"),
            "approval": result.get("approval"),
            "retry": result.get("retry"),
        },
    )
    session.messages.append(assistant_message)
    refresh_session_continuity_summary(session)

    return {
        "session": write_session(session),
        "workflow_result": result,
    }
