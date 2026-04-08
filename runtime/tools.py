from datetime import datetime, timezone
from pathlib import Path
from fnmatch import fnmatch

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


def repo_relative_path(path: Path) -> str:
    return path.resolve().relative_to(BASE_DIR.resolve()).as_posix()


def normalize_limit(value: object, *, field_name: str, default: int, maximum: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"Tool `{field_name}` must be a positive integer")
    return min(value, maximum)


def normalize_path_pattern(value: object) -> str:
    if value is None:
        return "*"
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Tool `pattern` must be a non-empty string when provided")
    return value.strip()


def truncate_text(value: object, *, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def list_files_tool(args: dict) -> dict:
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Tool `list_files` requires `path` to be a non-empty string")

    base_path = resolve_repo_path(raw_path)
    if not base_path.exists():
        raise FileNotFoundError(f"File not found: {raw_path}")
    if not base_path.is_dir():
        raise ValueError(f"Tool `list_files` requires a directory path: {raw_path}")

    pattern = normalize_path_pattern(args.get("pattern"))
    limit = normalize_limit(args.get("limit"), field_name="list_files.limit", default=200, maximum=1000)

    files = []
    for candidate in sorted(base_path.rglob("*")):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(base_path).as_posix()
        if not fnmatch(relative, pattern) and not fnmatch(candidate.name, pattern):
            continue
        files.append(repo_relative_path(candidate))
        if len(files) >= limit:
            break

    return {
        "path": repo_relative_path(base_path),
        "pattern": pattern,
        "limit": limit,
        "result_count": len(files),
        "files": files,
    }


def read_file_range_tool(args: dict) -> dict:
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Tool `read_file_range` requires `path` to be a non-empty string")

    start_line = args.get("start_line")
    if not isinstance(start_line, int) or start_line <= 0:
        raise ValueError("Tool `read_file_range` requires `start_line` to be a positive integer")

    end_line = args.get("end_line", start_line)
    if not isinstance(end_line, int) or end_line <= 0:
        raise ValueError("Tool `read_file_range` requires `end_line` to be a positive integer")
    if end_line < start_line:
        raise ValueError("Tool `read_file_range` requires `end_line` to be >= `start_line`")

    file_path = resolve_repo_path(raw_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {raw_path}")

    lines = file_path.read_text(encoding="utf-8").splitlines()
    selected = lines[start_line - 1 : end_line]
    return {
        "path": repo_relative_path(file_path),
        "start_line": start_line,
        "end_line": end_line,
        "line_count": len(selected),
        "content": "\n".join(selected),
    }


def search_files_tool(args: dict) -> dict:
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Tool `search_files` requires `path` to be a non-empty string")

    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Tool `search_files` requires `query` to be a non-empty string")

    base_path = resolve_repo_path(raw_path)
    if not base_path.exists():
        raise FileNotFoundError(f"File not found: {raw_path}")
    if not base_path.is_dir():
        raise ValueError(f"Tool `search_files` requires a directory path: {raw_path}")

    pattern = normalize_path_pattern(args.get("pattern"))
    limit = normalize_limit(args.get("limit"), field_name="search_files.limit", default=20, maximum=200)
    normalized_query = query.strip()
    hits = []

    for candidate in sorted(base_path.rglob("*")):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(base_path).as_posix()
        if not fnmatch(relative, pattern) and not fnmatch(candidate.name, pattern):
            continue

        try:
            contents = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for line_number, line in enumerate(contents.splitlines(), start=1):
            if normalized_query not in line:
                continue
            hits.append(
                {
                    "path": repo_relative_path(candidate),
                    "line_number": line_number,
                    "line": line,
                }
            )
            if len(hits) >= limit:
                return {
                    "path": repo_relative_path(base_path),
                    "query": normalized_query,
                    "pattern": pattern,
                    "limit": limit,
                    "result_count": len(hits),
                    "hits": hits,
                }

    return {
        "path": repo_relative_path(base_path),
        "query": normalized_query,
        "pattern": pattern,
        "limit": limit,
        "result_count": len(hits),
        "hits": hits,
    }


def inspect_session_tool(args: dict) -> dict:
    from runtime.control_plane import session_control_view

    session_id = args.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Tool `inspect_session` requires `session_id` to be a non-empty string")

    view = session_control_view(session_id.strip())
    messages = view.get("messages", [])
    recent_messages = [
        {
            "message_id": message.get("message_id"),
            "role": message.get("role"),
            "status": message.get("status"),
            "agent": message.get("agent"),
            "workflow_id": message.get("workflow_id"),
            "created_at": message.get("created_at"),
            "content_preview": truncate_text(message.get("content")),
        }
        for message in messages[-5:]
    ]
    current_workflow = view.get("current_workflow") or {}
    latest_incident = view.get("latest_incident") or {}
    continuity = view.get("continuity") or {}

    return {
        "session": {
            "session_id": view.get("session_id"),
            "title": view.get("title"),
            "status": view.get("status"),
            "agent": view.get("agent"),
            "current_workflow_id": view.get("current_workflow_id"),
            "workflow_count": len(view.get("workflow_ids", [])),
            "message_count": len(messages),
            "memory_scope": dict(view.get("memory_scope", {})),
        },
        "recent_messages": recent_messages,
        "workflow_rollup": dict(view.get("workflow_rollup", {})),
        "current_workflow": {
            "workflow_id": current_workflow.get("workflow_id"),
            "status": current_workflow.get("status"),
            "agent": current_workflow.get("agent"),
            "current_step": current_workflow.get("current_step"),
            "incident_rollup": current_workflow.get("incident_rollup"),
        }
        if current_workflow
        else None,
        "latest_incident": {
            "workflow_id": latest_incident.get("workflow_id"),
            "workflow_status": latest_incident.get("workflow_status"),
            "current_step": latest_incident.get("current_step"),
            "failure": latest_incident.get("failure"),
            "incident": latest_incident.get("incident", {}).get("rollup"),
        }
        if latest_incident
        else None,
        "continuity": {
            "scope": continuity.get("scope"),
            "recent_count": len(continuity.get("recent", [])),
            "workflow_recent_count": len(continuity.get("workflow_recent", [])),
            "message_memory_gap": continuity.get("message_memory_gap"),
        },
        "actions": dict(view.get("actions", {})),
    }


def inspect_workflow_tool(args: dict) -> dict:
    from runtime.control_plane import workflow_control_view

    workflow_id = args.get("workflow_id")
    if not isinstance(workflow_id, str) or not workflow_id.strip():
        raise ValueError("Tool `inspect_workflow` requires `workflow_id` to be a non-empty string")

    view = workflow_control_view(workflow_id.strip())
    current_step = view.get("current_step") or {}
    incident = view.get("incident") or {}

    return {
        "workflow": {
            "workflow_id": view.get("workflow_id"),
            "status": view.get("status"),
            "agent": view.get("agent"),
            "run_type": view.get("run_type"),
            "depth": view.get("depth"),
            "latest_run_id": view.get("latest_run_id"),
        },
        "current_step": {
            "step_id": current_step.get("step_id"),
            "step_type": current_step.get("step_type"),
            "status": current_step.get("status"),
            "details": current_step.get("details"),
            "error": current_step.get("error"),
        },
        "counts": {
            "artifact_count": len(view.get("artifacts", [])),
            "memory_count": len(view.get("memories", [])),
            "shared_memory_count": len(view.get("shared_memories", [])),
            "job_count": len(view.get("jobs", [])),
            "worker_count": len(view.get("workers", [])),
            "child_workflow_count": len(view.get("child_workflows", [])),
        },
        "recovery": dict(view.get("recovery", {})),
        "failure": view.get("failure"),
        "incident": {
            "trace_count": incident.get("trace_count"),
            "error_trace_count": incident.get("error_trace_count"),
            "classifications": incident.get("classifications"),
            "rollup": incident.get("rollup"),
            "recent_events": incident.get("recent_events", []),
        },
        "child_summary": dict(view.get("child_summary", {})),
        "actions": dict(view.get("actions", {})),
    }


def inspect_queue_tool(args: dict) -> dict:
    from runtime.queue import list_jobs, queue_health_summary

    limit = normalize_limit(args.get("limit"), field_name="inspect_queue.limit", default=10, maximum=50)
    status = args.get("status")
    if status is not None and (not isinstance(status, str) or not status.strip()):
        raise ValueError("Tool `inspect_queue` requires `status` to be a non-empty string when provided")

    jobs = list_jobs(status=status.strip() if isinstance(status, str) else None, promote_due=False)
    health = queue_health_summary()
    selected_jobs = jobs[:limit]

    return {
        "queue": {
            "total_jobs": health.get("total_jobs"),
            "counts": dict(health.get("counts", {})),
            "retry_pending_count": health.get("retry_pending_count"),
            "dead_letter_count": health.get("dead_letter_count"),
            "oldest_queued_at": health.get("oldest_queued_at"),
            "next_ready_at": health.get("next_ready_at"),
        },
        "health": {
            "retry_backlog_count": health.get("health", {}).get("retry_backlog_count"),
            "failed_count": health.get("health", {}).get("failed_count"),
            "dead_letter_count": health.get("health", {}).get("dead_letter_count"),
            "expired_running_count": health.get("health", {}).get("expired_running_count"),
            "recent_events": list(health.get("health", {}).get("trends", {}).get("recent_events", [])),
            "lifecycle": dict(health.get("health", {}).get("lifecycle", {})),
        },
        "jobs": [
            {
                "job_id": job.get("job_id"),
                "status": job.get("status"),
                "workflow_id": job.get("workflow_id"),
                "priority": job.get("priority"),
                "worker_id": job.get("worker_id"),
                "attempt_count": job.get("attempt_count"),
                "max_attempts": job.get("max_attempts"),
                "ready_at": job.get("ready_at"),
                "error": job.get("error"),
            }
            for job in selected_jobs
        ],
        "limit": limit,
        "status_filter": status.strip() if isinstance(status, str) else None,
    }


def inspect_worker_tool(args: dict) -> dict:
    from runtime.worker import load_worker, worker_health_summary, worker_summary

    worker_id = args.get("worker_id")
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ValueError("Tool `inspect_worker` requires `worker_id` to be a non-empty string")

    worker = worker_summary(load_worker(worker_id.strip()))
    health = worker_health_summary()

    return {
        "worker": {
            "worker_id": worker.get("worker_id"),
            "name": worker.get("name"),
            "status": worker.get("status"),
            "lease_seconds": worker.get("lease_seconds"),
            "lease_expired": worker.get("lease_expired"),
            "current_job_id": worker.get("current_job_id"),
            "last_heartbeat_at": worker.get("last_heartbeat_at"),
            "lease_expires_at": worker.get("lease_expires_at"),
        },
        "transition_history": list(worker.get("transition_history", [])[-10:]),
        "worker_health": {
            "counts": dict(health.get("counts", {})),
            "expired_worker_ids": list(health.get("expired_worker_ids", [])),
            "orphaned_worker_ids": list(health.get("orphaned_worker_ids", [])),
            "busy_worker_ids": list(health.get("busy_worker_ids", [])),
            "lifecycle": dict(health.get("lifecycle", {})),
            "trends": dict(health.get("trends", {})),
        },
    }


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
    "list_files": {
        "handler": list_files_tool,
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
