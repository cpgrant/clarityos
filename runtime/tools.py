from urllib import request

from runtime import tool_support
from runtime.contracts import build_tool_failure, build_tool_success
from runtime.tools_actions import (
    archive_session_tool,
    promote_ready_jobs_tool,
    prune_sessions_tool,
    recover_workflow_tool,
    repair_orphaned_workers_tool,
    repair_stale_jobs_tool,
    replay_workflow_tool,
    safe_resume_workflow_tool,
)
from runtime.tools_memory import memory_query_tool, memory_write_tool
from runtime.tools_repo import (
    list_directory_tool,
    list_files_tool,
    read_file_range_tool,
    read_file_tool,
    search_files_tool,
)
from runtime.tools_runtime import (
    inspect_queue_tool,
    inspect_session_tool,
    inspect_worker_tool,
    inspect_workflow_tool,
)
from runtime.tools_utility import echo_tool, get_time_tool
from runtime.tools_web import fetch_url_tool

BASE_DIR = tool_support.BASE_DIR


def _sync_tool_support() -> None:
    tool_support.BASE_DIR = BASE_DIR


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
    "list_files": {
        "handler": list_files_tool,
        "capability": "file_read",
        "path_arg": "path",
    },
    "list_directory": {
        "handler": list_directory_tool,
        "capability": "file_read",
        "path_arg": "path",
    },
    "read_file_range": {
        "handler": read_file_range_tool,
        "capability": "file_read",
        "path_arg": "path",
    },
    "search_files": {
        "handler": search_files_tool,
        "capability": "file_read",
        "path_arg": "path",
    },
    "fetch_url": {
        "handler": fetch_url_tool,
        "capability": "http",
        "domain_arg": "url",
    },
    "inspect_session": {
        "handler": inspect_session_tool,
        "capability": "runtime_read",
    },
    "inspect_workflow": {
        "handler": inspect_workflow_tool,
        "capability": "runtime_read",
    },
    "inspect_queue": {
        "handler": inspect_queue_tool,
        "capability": "runtime_read",
    },
    "inspect_worker": {
        "handler": inspect_worker_tool,
        "capability": "runtime_read",
    },
    "archive_session": {
        "handler": archive_session_tool,
        "capability": "runtime_write",
        "command": "archive_session",
    },
    "prune_sessions": {
        "handler": prune_sessions_tool,
        "capability": "runtime_write",
        "command": "prune_sessions",
    },
    "promote_ready_jobs": {
        "handler": promote_ready_jobs_tool,
        "capability": "runtime_write",
        "command": "promote_ready_jobs",
    },
    "repair_stale_jobs": {
        "handler": repair_stale_jobs_tool,
        "capability": "runtime_write",
        "command": "repair_stale_jobs",
    },
    "repair_orphaned_workers": {
        "handler": repair_orphaned_workers_tool,
        "capability": "runtime_write",
        "command": "repair_orphaned_workers",
    },
    "safe_resume_workflow": {
        "handler": safe_resume_workflow_tool,
        "capability": "runtime_write",
        "command": "safe_resume_workflow",
    },
    "replay_workflow": {
        "handler": replay_workflow_tool,
        "capability": "runtime_write",
        "command": "replay_workflow",
    },
    "recover_workflow": {
        "handler": recover_workflow_tool,
        "capability": "runtime_write",
        "command": "recover_workflow",
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
    _sync_tool_support()
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
