import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "memories"

MEMORY_TYPES = {"fact", "summary", "observation", "artifact_ref"}
MEMORY_SCOPE_KINDS = {"global", "agent", "workflow", "run"}
MEMORY_SCHEMAS = {
    "fact": {
        "required": {"statement"},
        "optional": {"subject"},
    },
    "summary": {
        "required": {"text"},
        "optional": {"source"},
    },
    "observation": {
        "required": {"text"},
        "optional": {"source"},
    },
    "artifact_ref": {
        "required": {"artifact_id"},
        "optional": {"description"},
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_memory_dir() -> None:
    MEMORY_DIR.mkdir(exist_ok=True)


def memory_path(memory_id: str) -> Path:
    return MEMORY_DIR / f"{memory_id}.json"


def normalize_non_empty_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Memory `{field_name}` must be a non-empty string")
    return value.strip()


def normalize_optional_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    return normalize_non_empty_string(value, field_name=field_name)


def normalize_positive_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"Memory `{field_name}` must be a positive integer")
    return value


def normalize_memory_type(memory_type: str) -> str:
    if memory_type not in MEMORY_TYPES:
        raise ValueError(f"Unknown memory type: {memory_type}")
    return memory_type


def normalize_scope_kind(scope_kind: str) -> str:
    if scope_kind not in MEMORY_SCOPE_KINDS:
        raise ValueError(f"Unknown memory scope kind: {scope_kind}")
    return scope_kind


def scope_value_for_kind(
    *,
    scope_kind: str,
    agent: str | None,
    workflow_id: str | None,
    run_id: str | None,
) -> str | None:
    scope_kind = normalize_scope_kind(scope_kind)
    if scope_kind == "global":
        return None
    if scope_kind == "agent":
        return normalize_non_empty_string(agent, field_name="agent")
    if scope_kind == "workflow":
        return normalize_non_empty_string(workflow_id, field_name="workflow_id")
    return normalize_non_empty_string(run_id, field_name="run_id")


def normalize_scope(
    *,
    scope_kind: str,
    agent: str | None,
    workflow_id: str | None,
    run_id: str | None,
) -> dict[str, str | None]:
    return {
        "kind": normalize_scope_kind(scope_kind),
        "value": scope_value_for_kind(
            scope_kind=scope_kind,
            agent=agent,
            workflow_id=workflow_id,
            run_id=run_id,
        ),
    }


def normalize_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, list):
        raise ValueError("Memory `tags` must be a list of strings")

    normalized = []
    seen = set()
    for raw_tag in tags:
        tag = normalize_non_empty_string(raw_tag, field_name="tags[]")
        if tag not in seen:
            normalized.append(tag)
            seen.add(tag)

    return normalized


def normalize_metadata(metadata: Any) -> dict[str, Any]:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise ValueError("Memory `metadata` must be an object")
    return dict(metadata)


def normalize_payload(memory_type: str, payload: Any) -> dict[str, Any]:
    memory_type = normalize_memory_type(memory_type)
    if not isinstance(payload, dict):
        raise ValueError("Memory `payload` must be an object")

    schema = MEMORY_SCHEMAS[memory_type]
    required = schema["required"]
    optional = schema["optional"]
    allowed = required | optional

    missing = [field for field in sorted(required) if field not in payload]
    if missing:
        raise ValueError(f"Memory `{memory_type}` payload is missing required fields: {', '.join(missing)}")

    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"Memory `{memory_type}` payload has unknown fields: {', '.join(unknown)}")

    normalized = {}
    for field in sorted(required):
        normalized[field] = normalize_non_empty_string(payload[field], field_name=f"payload.{field}")

    for field in sorted(optional):
        if field in payload and payload[field] is not None:
            normalized[field] = normalize_non_empty_string(payload[field], field_name=f"payload.{field}")

    return normalized


def memory_summary(memory: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "memory_id": memory["memory_id"],
        "memory_type": memory["memory_type"],
        "scope": dict(memory["scope"]),
        "agent": memory.get("agent"),
        "workflow_id": memory.get("workflow_id"),
        "run_id": memory.get("run_id"),
        "tags": list(memory.get("tags", [])),
        "created_at": memory["created_at"],
        "updated_at": memory["updated_at"],
        "metadata": dict(memory.get("metadata", {})),
        "payload_summary": memory.get("payload_summary", memory_payload_text(memory)),
    }
    artifact_id = memory.get("artifact_id") or memory.get("payload", {}).get("artifact_id")
    if isinstance(artifact_id, str) and artifact_id.strip():
        summary["artifact_id"] = artifact_id.strip()
    return summary


def memory_payload_text(memory: dict[str, Any]) -> str:
    payload = memory.get("payload", {})
    ordered_fields = []
    if memory["memory_type"] == "fact":
        ordered_fields = ["statement", "subject"]
    elif memory["memory_type"] == "summary":
        ordered_fields = ["text", "source"]
    elif memory["memory_type"] == "observation":
        ordered_fields = ["text", "source"]
    elif memory["memory_type"] == "artifact_ref":
        ordered_fields = ["description", "artifact_id"]

    values = []
    for field in ordered_fields:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())

    for field, value in payload.items():
        if field in ordered_fields:
            continue
        if isinstance(value, str) and value.strip():
            values.append(value.strip())

    return " | ".join(values)


def memory_search_text(memory: dict[str, Any]) -> str:
    parts = [
        memory["memory_type"],
        memory_payload_text(memory),
        " ".join(memory.get("tags", [])),
    ]

    for key in ("agent", "workflow_id", "run_id"):
        value = memory.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())

    return " ".join(part for part in parts if part).strip()


def query_tokens(query: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", query.lower())


def memory_match_score(memory: dict[str, Any], query: str, tokens: list[str]) -> tuple[float, list[str]]:
    haystack = memory_search_text(memory).lower()
    matched_terms = sorted({token for token in tokens if token in haystack})
    if not matched_terms:
        return 0.0, []

    score = float(len(matched_terms))
    if query.lower() in haystack:
        score += 2.0

    payload_text = memory_payload_text(memory).lower()
    if payload_text and query.lower() in payload_text:
        score += 1.0

    return score, matched_terms


def summarize_text(text: str, *, query: str, max_chars: int) -> str:
    if max_chars <= 3:
        return text[:max_chars]
    if len(text) <= max_chars:
        return text

    lowered_text = text.lower()
    lowered_query = query.lower()
    index = lowered_text.find(lowered_query)
    if index < 0:
        return text[: max_chars - 3].rstrip() + "..."

    start = max(index - max_chars // 3, 0)
    end = start + max_chars
    if end > len(text):
        end = len(text)
        start = max(end - max_chars, 0)

    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    if len(snippet) > max_chars:
        snippet = snippet[: max_chars - 3].rstrip() + "..."
    return snippet


def memory_source_summary(
    memory: dict[str, Any],
    *,
    query: str,
    matched_terms: list[str],
    score: float,
    max_summary_chars: int,
) -> dict[str, Any]:
    summary_text = summarize_text(memory_payload_text(memory), query=query, max_chars=max_summary_chars)
    return {
        "memory_id": memory["memory_id"],
        "memory_type": memory["memory_type"],
        "scope": dict(memory["scope"]),
        "agent": memory.get("agent"),
        "workflow_id": memory.get("workflow_id"),
        "run_id": memory.get("run_id"),
        "tags": list(memory.get("tags", [])),
        "created_at": memory["created_at"],
        "score": score,
        "matched_terms": matched_terms,
        "summary": summary_text,
    }


def write_memory(memory: dict[str, Any]) -> dict[str, Any]:
    ensure_memory_dir()
    path = memory_path(memory["memory_id"])
    with path.open("w", encoding="utf-8") as file:
        json.dump(memory, file, indent=2)
    return memory


def create_memory(
    *,
    memory_type: str,
    payload: dict[str, Any],
    scope_kind: str = "agent",
    agent: str | None = None,
    workflow_id: str | None = None,
    run_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = utc_now()
    memory = {
        "memory_id": str(uuid.uuid4()),
        "memory_type": normalize_memory_type(memory_type),
        "scope": normalize_scope(
            scope_kind=scope_kind,
            agent=agent,
            workflow_id=workflow_id,
            run_id=run_id,
        ),
        "agent": normalize_optional_string(agent, field_name="agent"),
        "workflow_id": normalize_optional_string(workflow_id, field_name="workflow_id"),
        "run_id": normalize_optional_string(run_id, field_name="run_id"),
        "payload": normalize_payload(memory_type, payload),
        "tags": normalize_tags(tags),
        "metadata": normalize_metadata(metadata),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    return write_memory(memory)


def load_memory(memory_id: str) -> dict[str, Any]:
    path = memory_path(memory_id)
    if not path.is_file():
        raise FileNotFoundError(f"Memory not found: {memory_id}")

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def update_memory(
    memory_id: str,
    *,
    payload: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = load_memory(memory_id)
    updated = dict(current)

    if payload is not None:
        updated["payload"] = normalize_payload(current["memory_type"], payload)
    if tags is not None:
        updated["tags"] = normalize_tags(tags)
    if metadata is not None:
        updated["metadata"] = normalize_metadata(metadata)

    updated["updated_at"] = utc_now()
    return write_memory(updated)


def memory_matches_filters(
    memory: dict[str, Any],
    *,
    memory_type: str | None = None,
    scope_kind: str | None = None,
    agent: str | None = None,
    workflow_id: str | None = None,
    run_id: str | None = None,
    tags: list[str] | None = None,
) -> bool:
    if memory_type is not None and memory["memory_type"] != normalize_memory_type(memory_type):
        return False
    if scope_kind is not None and memory["scope"]["kind"] != normalize_scope_kind(scope_kind):
        return False
    if agent is not None and memory.get("agent") != normalize_non_empty_string(agent, field_name="agent"):
        return False
    if workflow_id is not None and memory.get("workflow_id") != normalize_non_empty_string(
        workflow_id,
        field_name="workflow_id",
    ):
        return False
    if run_id is not None and memory.get("run_id") != normalize_non_empty_string(run_id, field_name="run_id"):
        return False
    if tags is not None:
        required_tags = set(normalize_tags(tags))
        if not required_tags.issubset(set(memory.get("tags", []))):
            return False
    return True


def list_memories(
    *,
    memory_type: str | None = None,
    scope_kind: str | None = None,
    agent: str | None = None,
    workflow_id: str | None = None,
    run_id: str | None = None,
    tags: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if limit is not None and (not isinstance(limit, int) or limit <= 0):
        raise ValueError("Memory `limit` must be a positive integer")
    if not MEMORY_DIR.is_dir():
        return []

    memories = []
    for path in sorted(MEMORY_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as file:
            memory = json.load(file)
        if memory_matches_filters(
            memory,
            memory_type=memory_type,
            scope_kind=scope_kind,
            agent=agent,
            workflow_id=workflow_id,
            run_id=run_id,
            tags=tags,
        ):
            memories.append(memory)

    memories.sort(key=lambda item: (item["created_at"], item["memory_id"]))
    if limit is not None:
        return memories[:limit]
    return memories


def query_memories(
    *,
    query: str,
    memory_type: str | None = None,
    scope_kind: str | None = None,
    agent: str | None = None,
    workflow_id: str | None = None,
    run_id: str | None = None,
    tags: list[str] | None = None,
    limit: int = 5,
    max_chars: int = 1200,
    max_summary_chars: int = 240,
) -> dict[str, Any]:
    normalized_query = normalize_non_empty_string(query, field_name="query")
    limit = normalize_positive_int(limit, field_name="limit")
    max_chars = normalize_positive_int(max_chars, field_name="max_chars")
    max_summary_chars = normalize_positive_int(max_summary_chars, field_name="max_summary_chars")

    tokens = query_tokens(normalized_query)
    if not tokens:
        raise ValueError("Memory `query` must contain searchable text")

    candidates = []
    for memory in list_memories(
        memory_type=memory_type,
        scope_kind=scope_kind,
        agent=agent,
        workflow_id=workflow_id,
        run_id=run_id,
        tags=tags,
    ):
        score, matched_terms = memory_match_score(memory, normalized_query, tokens)
        if score <= 0:
            continue
        candidates.append((score, matched_terms, memory))

    candidates.sort(key=lambda item: (-item[0], item[2]["created_at"], item[2]["memory_id"]))

    results = []
    used_chars = 0
    truncated = False
    for score, matched_terms, matched_memory in candidates:
        if len(results) >= limit:
            truncated = True
            break

        summary = memory_source_summary(
            matched_memory,
            query=normalized_query,
            matched_terms=matched_terms,
            score=round(score, 2),
            max_summary_chars=max_summary_chars,
        )
        summary_chars = len(summary["summary"])
        if results and used_chars + summary_chars > max_chars:
            truncated = True
            break
        if not results and summary_chars > max_chars:
            summary["summary"] = summarize_text(
                memory_payload_text(matched_memory),
                query=normalized_query,
                max_chars=max_chars,
            )
            summary_chars = len(summary["summary"])

        used_chars += summary_chars
        results.append(summary)

    return {
        "query": normalized_query,
        "filters": {
            "memory_type": memory_type,
            "scope_kind": scope_kind,
            "agent": agent,
            "workflow_id": workflow_id,
            "run_id": run_id,
            "tags": normalize_tags(tags),
        },
        "limit": limit,
        "max_chars": max_chars,
        "max_summary_chars": max_summary_chars,
        "result_count": len(results),
        "used_chars": used_chars,
        "truncated": truncated,
        "results": results,
    }


def delete_memory(memory_id: str) -> dict[str, Any]:
    memory = load_memory(memory_id)
    memory_path(memory_id).unlink()
    return memory
