import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.storage import LOG_DIR
TRACE_VERSION = "v0.8"
TRACE_SCHEMA = "trace.v2"


def ensure_log_dir() -> None:
    LOG_DIR.mkdir(exist_ok=True)


def trace_run(data: dict) -> Path:
    ensure_log_dir()

    timestamp = datetime.now(timezone.utc)
    filename_timestamp = timestamp.isoformat().replace(":", "-")
    log_path = LOG_DIR / f"run_{filename_timestamp}.json"

    trace_payload = {
        "version": TRACE_VERSION,
        "schema": TRACE_SCHEMA,
        "timestamp": timestamp.isoformat(),
        **data,
    }

    with log_path.open("w", encoding="utf-8") as file:
        json.dump(trace_payload, file, indent=2)

    return log_path


def load_trace(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def trace_summary(trace: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    workflow = trace.get("workflow") or {}
    result = trace.get("result") or {}
    error = result.get("error")
    if error is None:
        error = trace.get("error")
    correlation_ids = trace.get("correlation_ids")
    if not isinstance(correlation_ids, dict):
        correlation_ids = {
            "run_ids": [value for value in [trace.get("run_id"), trace.get("parent_run_id"), workflow.get("latest_run_id")] if value],
            "workflow_ids": [value for value in [workflow.get("workflow_id")] if value],
            "job_ids": [],
            "worker_ids": [],
            "approval_ids": [],
            "artifact_ids": [],
            "memory_ids": [],
            "shared_memory_ids": [],
            "child_workflow_ids": [],
            "delegation": {},
        }
    classification = trace_failure_classification(
        status=trace.get("status"),
        error=error,
    )
    return {
        "trace_id": path.name if path is not None else None,
        "path": str(path) if path is not None else None,
        "timestamp": trace.get("timestamp"),
        "status": trace.get("status"),
        "run_id": trace.get("run_id"),
        "parent_run_id": trace.get("parent_run_id"),
        "agent": trace.get("agent"),
        "workflow_id": workflow.get("workflow_id"),
        "latest_run_id": workflow.get("latest_run_id"),
        "workflow_status": workflow.get("status"),
        "correlation_ids": correlation_ids,
        "error": error,
        "failure_classification": classification,
    }


def trace_failure_classification(*, status: str | None, error: dict[str, Any] | None) -> str | None:
    if status == "retry_wait":
        return "retry_wait"
    if error is None:
        return None

    error_type = error.get("error_type") or error.get("type")
    failure_type = error.get("failure_type")
    message = str(error.get("message", "")).lower()

    if error_type == "PolicyDeniedError":
        return "policy_denied"
    if error_type == "DelegationDeniedError":
        return "delegation_denied"
    if error_type == "BudgetExceededError":
        return "budget_exhausted"
    if error_type == "ApprovalStateError" or "approval" in message:
        return "approval_blocked"
    if failure_type == "tool_error":
        return "tool_error"
    if error_type in {"TimeoutError", "ConnectionError"}:
        return "transient_runtime"
    return "runtime_error"


def trace_timeline_event(trace: dict[str, Any]) -> dict[str, Any]:
    error = trace.get("error")
    message = None
    if isinstance(error, dict):
        message = error.get("message")
    return {
        "source": "trace",
        "entity_id": trace.get("trace_id"),
        "event_id": trace.get("trace_id"),
        "event_type": "trace_recorded",
        "timestamp": trace.get("timestamp"),
        "status": trace.get("status"),
        "run_id": trace.get("run_id"),
        "workflow_id": trace.get("workflow_id"),
        "latest_run_id": trace.get("latest_run_id"),
        "failure_classification": trace.get("failure_classification"),
        "message": message,
        "correlation_ids": trace.get("correlation_ids", {}),
    }


def trace_timeline(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [trace_timeline_event(trace) for trace in traces]


def list_traces(*, limit: int | None = None) -> list[dict[str, Any]]:
    if limit is not None and (not isinstance(limit, int) or limit <= 0):
        raise ValueError("Trace `limit` must be a positive integer")
    if not LOG_DIR.is_dir():
        return []

    traces = []
    for path in sorted(LOG_DIR.glob("run_*.json"), reverse=True):
        trace = load_trace(path)
        traces.append(trace_summary(trace, path=path))
        if limit is not None and len(traces) >= limit:
            break
    return traces
