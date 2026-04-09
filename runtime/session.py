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

    prompt_context = build_assistant_prompt_context(
        surface=session.ownership.get("surface"),
        user_input=normalized_content,
        agent_name=message_agent,
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

    return {
        "session": write_session(session),
        "workflow_result": result,
    }
