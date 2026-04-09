from runtime.tool_support import normalize_limit, truncate_text


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
        "summary": (
            f"Session {view.get('session_id')} is {view.get('status')} with {len(messages)} messages "
            f"and {len(view.get('workflow_ids', []))} related workflows"
        ),
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
        "summary": (
            f"Workflow {view.get('workflow_id')} is {view.get('status')} "
            f"at step {current_step.get('step_type')} ({current_step.get('status')})"
        ),
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
        "summary": (
            f"Queue has {health.get('total_jobs')} jobs, "
            f"{health.get('dead_letter_count')} dead-lettered, "
            f"and {health.get('retry_pending_count')} waiting to retry"
        ),
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
        "summary": (
            f"Worker {worker.get('worker_id')} is {worker.get('status')} "
            f"with current job {worker.get('current_job_id')}"
        ),
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
