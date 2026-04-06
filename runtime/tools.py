from datetime import datetime, timezone
from pathlib import Path

from runtime.contracts import build_tool_failure, build_tool_success

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
