from datetime import datetime, timezone
from pathlib import Path

from runtime.contracts import build_tool_failure, build_tool_success
from runtime.memory import create_memory, query_memories

BASE_DIR = Path(__file__).resolve().parent.parent


def echo_tool(args: dict) -> str:
    text = args.get("text", "")
    if not isinstance(text, str):
        raise ValueError("Tool `echo` requires `text` to be a string")

    return text


def get_time_tool(args: dict) -> dict:
    _ = args

    timestamp = datetime.now(timezone.utc)
    return {
        "utc": timestamp.isoformat(),
    }


def resolve_repo_path(raw_path: str) -> Path:
    repo_root = BASE_DIR.resolve()
    candidate = Path(raw_path)

    if not candidate.is_absolute():
        candidate = repo_root / candidate

    resolved_path = candidate.resolve()

    try:
        resolved_path.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError("Tool `read_file` only allows files inside the repo") from exc

    return resolved_path


def read_file_tool(args: dict) -> str:
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Tool `read_file` requires `path` to be a non-empty string")

    file_path = resolve_repo_path(raw_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {raw_path}")

    return file_path.read_text(encoding="utf-8")


def memory_write_tool(args: dict) -> dict:
    memory_type = args.get("memory_type")
    payload = args.get("payload")
    scope_kind = args.get("scope_kind", "agent")
    agent = args.get("agent")
    workflow_id = args.get("workflow_id")
    run_id = args.get("run_id")
    tags = args.get("tags")
    metadata = args.get("metadata")

    return create_memory(
        memory_type=memory_type,
        payload=payload,
        scope_kind=scope_kind,
        agent=agent,
        workflow_id=workflow_id,
        run_id=run_id,
        tags=tags,
        metadata=metadata,
    )


def memory_query_tool(args: dict) -> dict:
    scope_kind = args.get("scope_kind")
    if not isinstance(scope_kind, str) or not scope_kind.strip():
        raise ValueError("Tool `memory_query` requires `scope_kind` to be a non-empty string")

    return query_memories(
        query=args.get("query", ""),
        memory_type=args.get("memory_type"),
        scope_kind=scope_kind,
        agent=args.get("agent"),
        workflow_id=args.get("workflow_id"),
        run_id=args.get("run_id"),
        tags=args.get("tags"),
        limit=args.get("limit", 5),
        max_chars=args.get("max_chars", 1200),
        max_summary_chars=args.get("max_summary_chars", 240),
    )


TOOLS = {
    "echo": {
        "handler": echo_tool,
        "capability": "exec",
        "command": "echo",
    },
    "get_time": {
        "handler": get_time_tool,
        "capability": "exec",
        "command": "get_time",
    },
    "read_file": {
        "handler": read_file_tool,
        "capability": "file_read",
        "path_arg": "path",
    },
    "memory_write": {
        "handler": memory_write_tool,
        "capability": "memory_write",
    },
    "memory_query": {
        "handler": memory_query_tool,
        "capability": "memory_read",
    },
}


def list_tools() -> list[str]:
    return sorted(TOOLS)


def get_tool_definition(name: str) -> dict:
    if name not in TOOLS:
        raise ValueError(f"Unknown tool: {name}")

    return TOOLS[name]


def call_tool(name: str, args: dict | None = None) -> dict:
    tool_definition = get_tool_definition(name)

    if args is None:
        args = {}

    if not isinstance(args, dict):
        raise ValueError("Tool arguments must be an object")

    try:
        output = tool_definition["handler"](args)
    except Exception as exc:
        return build_tool_failure(name=name, args=args, exc=exc)

    return build_tool_success(name=name, args=args, output=output)
