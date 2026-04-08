from datetime import datetime, timezone

from runtime.approval import approval_summary, list_approvals_for_workflow
from runtime.artifact import artifact_summary, list_artifacts_for_workflow
from runtime.memory import list_memories, memory_summary
from runtime.queue import job_lease_expired, list_jobs, queue_health_summary, requeue_job, reschedule_job
from runtime.session import list_sessions, load_session, session_snapshot
from runtime.trace import list_traces, trace_timeline
from runtime.worker import load_worker, update_worker, worker_health_summary
from runtime.workflow import can_spawn_child_workflow, current_step, load_workflow, workflow_snapshot


def event_sort_key(event: dict) -> tuple[datetime, str, str]:
    timestamp = event.get("timestamp")
    if timestamp is None:
        parsed = datetime.min.replace(tzinfo=timezone.utc)
    else:
        parsed = datetime.fromisoformat(timestamp)
    return (parsed, event.get("source", ""), event.get("event_id", ""))


def unique_ids(values: list[str | None]) -> list[str]:
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


def classify_error(error: dict | None) -> str | None:
    if error is None:
        return None
    error_type = error.get("error_type") or error.get("type")
    message = str(error.get("message", "")).lower()
    if error_type == "PolicyDeniedError":
        return "policy_denied"
    if error_type == "DelegationDeniedError":
        return "delegation_denied"
    if error_type == "BudgetExceededError":
        return "budget_exhausted"
    if error_type == "ApprovalStateError" or "approval" in message:
        return "approval_blocked"
    if error_type in {"TimeoutError", "ConnectionError"}:
        return "transient_runtime"
    return "runtime_error"


def workflow_failure_view(workflow) -> dict | None:
    if workflow.status != "failed":
        return None

    step = current_step(workflow)
    error = dict(step.error) if step.error is not None else None
    if error is None:
        for candidate in reversed(workflow.steps):
            if candidate.error is not None:
                error = dict(candidate.error)
                break

    return {
        "workflow_id": workflow.workflow_id,
        "step_id": step.step_id,
        "step_type": step.step_type,
        "error": error,
        "failure_classification": classify_error(error),
        "path": f"/workflows/{workflow.workflow_id}",
    }


def child_workflow_view(workflow) -> dict:
    step = current_step(workflow)
    return {
        **workflow_snapshot(workflow),
        "path": f"/workflows/{workflow.workflow_id}",
        "current_step": {
            "step_id": step.step_id,
            "step_type": step.step_type,
            "status": step.status,
            "details": dict(step.details),
            "error": dict(step.error) if step.error is not None else None,
        },
        "failure": workflow_failure_view(workflow),
    }


def child_workflow_views(workflow) -> tuple[list[dict], list[str]]:
    children = []
    missing = []
    for child_workflow_id in workflow.child_workflow_ids:
        try:
            children.append(child_workflow_view(load_workflow(child_workflow_id)))
        except FileNotFoundError:
            missing.append(child_workflow_id)

    return children, missing


def child_workflow_summary(workflow, children: list[dict], missing_child_workflow_ids: list[str]) -> dict:
    status_counts = {
        "running": 0,
        "waiting": 0,
        "succeeded": 0,
        "failed": 0,
        "missing": len(missing_child_workflow_ids),
    }
    failed_children = []
    for child in children:
        status = child["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        if child.get("failure") is not None:
            failed_children.append(
                {
                    "workflow_id": child["workflow_id"],
                    "agent": child["agent"],
                    "role": child.get("delegation", {}).get("role"),
                    "path": child["path"],
                    "error": dict(child["failure"]["error"]) if child["failure"]["error"] is not None else None,
                    "step_id": child["failure"]["step_id"],
                    "step_type": child["failure"]["step_type"],
                    "isolated_from_parent": workflow.status != "failed",
                }
            )

    isolation_state = "clear"
    if failed_children and workflow.status != "failed":
        isolation_state = "contained"
    elif failed_children and workflow.status == "failed":
        isolation_state = "parent_failed"

    return {
        "status_counts": status_counts,
        "failed_children": failed_children,
        "missing_child_workflow_ids": list(missing_child_workflow_ids),
        "isolation_state": isolation_state,
        "parent_status": workflow.status,
    }


def job_relates_to_workflow(job: dict, workflow) -> bool:
    if job.get("workflow_id") == workflow.workflow_id:
        return True

    payload = job.get("payload", {})
    if isinstance(payload, dict) and payload.get("workflow_id") == workflow.workflow_id:
        return True

    result = job.get("result", {})
    if isinstance(result, dict):
        workflow_result = result.get("workflow", {})
        if isinstance(workflow_result, dict) and workflow_result.get("workflow_id") == workflow.workflow_id:
            return True

    return False


def related_jobs_for_workflow(workflow) -> list[dict]:
    jobs = [job for job in list_jobs(promote_due=False) if job_relates_to_workflow(job, workflow)]
    jobs.sort(key=lambda job: (job["created_at"], job["job_id"]))
    return jobs


def related_workers_for_jobs(jobs: list[dict]) -> tuple[list[dict], list[str]]:
    workers = []
    missing_worker_ids = []
    seen = set()
    for job in jobs:
        worker_id = job.get("worker_id")
        if worker_id is None or worker_id in seen:
            continue
        seen.add(worker_id)
        try:
            workers.append(load_worker(worker_id))
        except FileNotFoundError:
            missing_worker_ids.append(worker_id)
    return workers, missing_worker_ids


def workflow_recovery_summary(workflow, jobs: list[dict], workers: list[dict], missing_worker_ids: list[str]) -> dict:
    expired_running_job_ids = [job["job_id"] for job in jobs if job_lease_expired(job)]
    failed_job_ids = [job["job_id"] for job in jobs if job["status"] == "failed"]
    dead_letter_job_ids = [job["job_id"] for job in jobs if job["status"] == "dead_letter"]
    retry_scheduled_job_ids = [job["job_id"] for job in jobs if job["status"] == "scheduled" and job.get("attempt_count", 0) > 0]
    busy_worker_ids = [worker["worker_id"] for worker in workers if worker.get("current_job_id") is not None]
    expired_worker_ids = [worker["worker_id"] for worker in workers if worker.get("lease_expired")]

    return {
        "related_job_count": len(jobs),
        "related_worker_count": len(workers),
        "missing_worker_ids": missing_worker_ids,
        "expired_running_job_ids": expired_running_job_ids,
        "failed_job_ids": failed_job_ids,
        "dead_letter_job_ids": dead_letter_job_ids,
        "retry_scheduled_job_ids": retry_scheduled_job_ids,
        "busy_worker_ids": busy_worker_ids,
        "expired_worker_ids": expired_worker_ids,
        "recoverable_job_ids": failed_job_ids + dead_letter_job_ids,
        "has_recovery_actions": bool(expired_running_job_ids or failed_job_ids or dead_letter_job_ids),
        "can_safe_resume": workflow.status == "waiting" and current_step(workflow).step_type in {"approval_wait", "retry_wait"},
        "can_replay": workflow.status == "failed" and bool(workflow.request),
        "workflow_status": workflow.status,
    }


def trace_relates_to_workflow(
    trace: dict,
    workflow,
    related_run_ids: set[str],
    related_workflow_ids: set[str],
    related_child_workflow_ids: set[str],
) -> bool:
    correlation = trace.get("correlation_ids", {})
    trace_run_ids = set(correlation.get("run_ids", []))
    trace_workflow_ids = set(correlation.get("workflow_ids", []))
    trace_child_workflow_ids = set(correlation.get("child_workflow_ids", []))
    delegation = correlation.get("delegation", {})

    workflow_id = trace.get("workflow_id")
    latest_run_id = trace.get("latest_run_id")
    run_id = trace.get("run_id")
    parent_run_id = trace.get("parent_run_id")
    assigned_by_workflow_id = delegation.get("assigned_by_workflow_id")
    assigned_by_run_id = delegation.get("assigned_by_run_id")

    return (
        workflow_id in related_workflow_ids
        or latest_run_id in related_run_ids
        or run_id in related_run_ids
        or parent_run_id in related_run_ids
        or assigned_by_workflow_id in related_workflow_ids
        or assigned_by_run_id in related_run_ids
        or bool(trace_run_ids & related_run_ids)
        or bool(trace_workflow_ids & related_workflow_ids)
        or bool(trace_child_workflow_ids & related_child_workflow_ids)
    )


def classify_job_event(job: dict) -> str | None:
    if job_lease_expired(job):
        return "expired_running_job"
    if job["status"] == "dead_letter":
        return "dead_letter"
    if job["status"] == "failed":
        return "job_failed"
    if job["status"] == "scheduled" and job.get("attempt_count", 0) > 0:
        return "retry_pending"
    if job.get("reclaim_count", 0) > 0:
        return "job_reclaimed"
    return None


def classify_worker_event(worker: dict, jobs_by_id: dict[str, dict]) -> str | None:
    if worker.get("lease_expired"):
        return "worker_lease_expired"
    current_job_id = worker.get("current_job_id")
    if current_job_id is None and worker.get("status") != "idle":
        return "worker_orphaned"
    if current_job_id is None:
        return None
    job = jobs_by_id.get(current_job_id)
    if job is None:
        return "worker_orphaned"
    if job["status"] != "running" or job.get("worker_id") != worker["worker_id"]:
        return "worker_orphaned"
    return None


def related_trace_summaries_for_workflow(workflow, *, limit: int = 20) -> list[dict]:
    if not isinstance(limit, int) or limit <= 0:
        raise ValueError("Workflow incident `limit` must be a positive integer")

    related_run_ids = set(unique_ids([workflow.run_id, workflow.latest_run_id]))
    related_workflow_ids = set(
        unique_ids([workflow.workflow_id, workflow.root_workflow_id, workflow.parent_workflow_id])
    )
    related_child_workflow_ids = set(workflow.child_workflow_ids)
    if workflow.delegation:
        related_run_ids.update(unique_ids([workflow.delegation.get("assigned_by_run_id")]))
        related_workflow_ids.update(
            unique_ids([workflow.delegation.get("assigned_by_workflow_id")])
        )

    traces = []
    for trace in list_traces():
        if trace_relates_to_workflow(
            trace,
            workflow,
            related_run_ids,
            related_workflow_ids,
            related_child_workflow_ids,
        ):
            traces.append(trace)
        if len(traces) >= limit:
            break
    return traces


def incident_trace_summary(traces: list[dict]) -> dict:
    status_counts = {}
    error_traces = []
    classification_counts = {}
    for trace in traces:
        status = trace.get("status") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        classification = trace.get("failure_classification")
        if classification is not None:
            classification_counts[classification] = classification_counts.get(classification, 0) + 1
        if trace.get("error") is not None:
            error_traces.append(
                {
                    "trace_id": trace["trace_id"],
                    "timestamp": trace["timestamp"],
                    "status": trace["status"],
                    "run_id": trace["run_id"],
                    "error": dict(trace["error"]),
                    "failure_classification": classification,
                }
            )

    latest_trace = traces[0] if traces else None
    return {
        "trace_count": len(traces),
        "status_counts": status_counts,
        "classification_counts": classification_counts,
        "latest_trace": latest_trace,
        "error_trace_count": len(error_traces),
        "error_traces": error_traces,
    }


def workflow_incident_events(workflow, jobs: list[dict], workers: list[dict], traces: list[dict]) -> list[dict]:
    events = []
    workflow_failure = workflow_failure_view(workflow)
    if workflow_failure is not None:
        events.append(
            {
                "source": "workflow",
                "event_id": workflow.workflow_id,
                "timestamp": workflow.updated_at,
                "failure_classification": workflow_failure.get("failure_classification"),
                "status": workflow.status,
                "message": (workflow_failure.get("error") or {}).get("message"),
            }
        )

    for job in jobs:
        classification = classify_job_event(job)
        if classification is None:
            continue
        events.append(
            {
                "source": "job",
                "event_id": job["job_id"],
                "timestamp": job.get("dead_lettered_at") or job.get("last_failure_at") or job.get("next_retry_at") or job["updated_at"],
                "failure_classification": classification,
                "status": job["status"],
                "message": (job.get("error") or {}).get("message") or job.get("last_requeue_reason"),
            }
        )

    jobs_by_id = {job["job_id"]: job for job in jobs}
    for worker in workers:
        classification = classify_worker_event(worker, jobs_by_id)
        if classification is None:
            continue
        events.append(
            {
                "source": "worker",
                "event_id": worker["worker_id"],
                "timestamp": worker.get("lease_expires_at") or worker["updated_at"],
                "failure_classification": classification,
                "status": worker["status"],
                "message": f"Worker `{worker['worker_id']}` requires operator attention",
            }
        )

    for trace in traces:
        if trace.get("failure_classification") is None:
            continue
        events.append(
            {
                "source": "trace",
                "event_id": trace["trace_id"],
                "timestamp": trace["timestamp"],
                "failure_classification": trace["failure_classification"],
                "status": trace["status"],
                "message": (trace.get("error") or {}).get("message"),
            }
        )

    events.sort(key=event_sort_key, reverse=True)
    return events


def incident_classification_summary(events: list[dict]) -> dict:
    counts = {}
    by_source = {}
    for event in events:
        classification = event.get("failure_classification")
        if classification is None:
            continue
        counts[classification] = counts.get(classification, 0) + 1
        source = event["source"]
        source_counts = by_source.setdefault(source, {})
        source_counts[classification] = source_counts.get(classification, 0) + 1
    return {
        "counts": counts,
        "by_source": by_source,
    }


def timeline_event(source: str, entity_id: str, entry: dict) -> dict:
    return {
        "source": source,
        "entity_id": entity_id,
        "event_id": f"{source}:{entity_id}:{entry.get('timestamp', '')}:{entry.get('event_type', '')}",
        "timestamp": entry.get("timestamp"),
        **dict(entry),
    }


def merged_timeline_events(*event_groups: list[dict]) -> list[dict]:
    merged = []
    seen = set()
    for events in event_groups:
        for event in events:
            event_id = (
                event.get("event_id"),
                event.get("source"),
                event.get("timestamp"),
                event.get("event_type"),
            )
            if event_id in seen:
                continue
            merged.append(dict(event))
            seen.add(event_id)
    merged.sort(key=event_sort_key, reverse=True)
    return merged


def event_failure_classification(event: dict) -> str | None:
    classification = event.get("failure_classification")
    if classification is not None:
        return classification
    event_type = event.get("event_type")
    status = event.get("status")
    if event_type in {"failed", "dead_lettered"} or status in {"failed", "dead_letter"}:
        return "runtime_error"
    if event_type == "retry_scheduled":
        return "retry_wait"
    if event_type in {"worker_orphaned", "expired_worker"}:
        return "transient_runtime"
    return None


def event_is_recovery_attempt(event: dict) -> bool:
    return event.get("event_type") in {
        "requeued",
        "rescheduled",
        "retry_scheduled",
        "job_released",
        "heartbeat",
        "reclaimed",
    } or event.get("failure_classification") in {"retry_pending", "job_reclaimed"}


def current_blocker_summary(
    workflow,
    recovery: dict,
    incident_events: list[dict],
    causality_chain: list[dict],
) -> dict | None:
    step = current_step(workflow)
    if workflow.status == "waiting" and step.step_type == "approval_wait":
        return {
            "kind": "approval_wait",
            "step_id": step.step_id,
            "message": f"Workflow `{workflow.workflow_id}` is blocked on approval",
        }
    if workflow.status == "waiting" and step.step_type == "retry_wait":
        next_retry_at = step.details.get("next_retry_at")
        return {
            "kind": "retry_wait",
            "step_id": step.step_id,
            "next_retry_at": next_retry_at,
            "message": f"Workflow `{workflow.workflow_id}` is waiting for retry eligibility",
        }
    if recovery["expired_running_job_ids"]:
        return {
            "kind": "expired_running_job",
            "job_ids": list(recovery["expired_running_job_ids"]),
            "message": "Related running jobs have expired leases",
        }
    if recovery["missing_worker_ids"]:
        return {
            "kind": "missing_worker",
            "worker_ids": list(recovery["missing_worker_ids"]),
            "message": "Related jobs reference missing workers",
        }
    if incident_events:
        latest = incident_events[0]
        return {
            "kind": latest.get("failure_classification") or latest.get("event_type") or latest.get("source"),
            "event_id": latest.get("event_id"),
            "message": latest.get("message"),
        }
    if causality_chain:
        latest = causality_chain[0]
        return {
            "kind": latest.get("event_type") or latest.get("source"),
            "event_id": latest.get("event_id"),
            "message": latest.get("message"),
        }
    return None


def incident_rollup(
    workflow,
    *,
    recovery: dict,
    incident_events: list[dict],
    causality_chain: list[dict],
) -> dict:
    chronological = sorted(causality_chain, key=event_sort_key)
    first_failure = next(
        (event for event in chronological if event_failure_classification(event) is not None),
        None,
    )
    latest_recovery_attempt = next(
        (event for event in causality_chain if event_is_recovery_attempt(event)),
        None,
    )
    latest_failure = next(
        (event for event in causality_chain if event_failure_classification(event) is not None),
        None,
    )
    blocker = current_blocker_summary(workflow, recovery, incident_events, causality_chain)

    return {
        "first_failure": first_failure,
        "latest_failure": latest_failure,
        "latest_recovery_attempt": latest_recovery_attempt,
        "current_blocker": blocker,
        "causal_chain": causality_chain[:10],
    }


def workflow_transition_timelines(workflow, jobs: list[dict], workers: list[dict]) -> dict:
    workflow_history = [dict(entry) for entry in workflow.transition_history]
    job_histories = {
        job["job_id"]: [dict(entry) for entry in job.get("transition_history", [])]
        for job in jobs
    }
    worker_histories = {
        worker["worker_id"]: [dict(entry) for entry in worker.get("transition_history", [])]
        for worker in workers
    }

    recent = [timeline_event("workflow", workflow.workflow_id, entry) for entry in workflow_history]
    for job_id, history in job_histories.items():
        recent.extend(timeline_event("job", job_id, entry) for entry in history)
    for worker_id, history in worker_histories.items():
        recent.extend(timeline_event("worker", worker_id, entry) for entry in history)

    recent.sort(key=event_sort_key, reverse=True)
    return {
        "workflow": workflow_history[-20:],
        "jobs": {job_id: history[-20:] for job_id, history in job_histories.items()},
        "workers": {worker_id: history[-20:] for worker_id, history in worker_histories.items()},
        "recent": recent[:25],
    }


def workflow_correlation_ids(workflow, approvals: list[dict], jobs: list[dict], workers: list[dict], traces: list[dict]) -> dict:
    run_ids = [
        workflow.run_id,
        workflow.latest_run_id,
        workflow.delegation.get("assigned_by_run_id"),
    ]
    workflow_ids = [
        workflow.workflow_id,
        workflow.root_workflow_id,
        workflow.parent_workflow_id,
        workflow.delegation.get("assigned_by_workflow_id"),
    ]
    job_ids = [job["job_id"] for job in jobs]
    worker_ids = [worker["worker_id"] for worker in workers]
    approval_ids = [approval["approval_id"] for approval in approvals]
    artifact_ids = [artifact.get("artifact_id") for artifact in workflow.artifacts]
    memory_ids = [memory.get("memory_id") for memory in workflow.memories]
    shared_memory_ids = [memory.get("memory_id") for memory in workflow.shared_memories]
    child_workflow_ids = list(workflow.child_workflow_ids)
    trace_ids = [trace.get("trace_id") for trace in traces]
    delegation_workflow_ids = [workflow.delegation.get("assigned_by_workflow_id")]
    delegation_run_ids = [workflow.delegation.get("assigned_by_run_id")]

    for trace in traces:
        correlation = trace.get("correlation_ids", {})
        run_ids.extend(correlation.get("run_ids", []))
        workflow_ids.extend(correlation.get("workflow_ids", []))
        job_ids.extend(correlation.get("job_ids", []))
        worker_ids.extend(correlation.get("worker_ids", []))
        approval_ids.extend(correlation.get("approval_ids", []))
        artifact_ids.extend(correlation.get("artifact_ids", []))
        memory_ids.extend(correlation.get("memory_ids", []))
        shared_memory_ids.extend(correlation.get("shared_memory_ids", []))
        child_workflow_ids.extend(correlation.get("child_workflow_ids", []))
        delegation = correlation.get("delegation", {})
        delegation_workflow_ids.append(delegation.get("assigned_by_workflow_id"))
        delegation_run_ids.append(delegation.get("assigned_by_run_id"))

    return {
        "run_ids": unique_ids(run_ids),
        "workflow_ids": unique_ids(workflow_ids),
        "job_ids": unique_ids(job_ids),
        "worker_ids": unique_ids(worker_ids),
        "approval_ids": unique_ids(approval_ids),
        "artifact_ids": unique_ids(artifact_ids),
        "memory_ids": unique_ids(memory_ids),
        "shared_memory_ids": unique_ids(shared_memory_ids),
        "child_workflow_ids": unique_ids(child_workflow_ids),
        "trace_ids": unique_ids(trace_ids),
        "delegation": {
            "assigned_by_workflow_ids": unique_ids(delegation_workflow_ids),
            "assigned_by_run_ids": unique_ids(delegation_run_ids),
        },
    }


def workflow_incident_view(workflow_id: str, *, trace_limit: int = 20) -> dict:
    workflow = load_workflow(workflow_id)
    approvals = [approval_summary(approval) for approval in list_approvals_for_workflow(workflow_id)]
    jobs = related_jobs_for_workflow(workflow)
    workers, missing_worker_ids = related_workers_for_jobs(jobs)
    traces = related_trace_summaries_for_workflow(workflow, limit=trace_limit)
    incident_traces = incident_trace_summary(traces)
    events = workflow_incident_events(workflow, jobs, workers, traces)
    classifications = incident_classification_summary(events)
    correlation_ids = workflow_correlation_ids(workflow, approvals, jobs, workers, traces)
    timelines = workflow_transition_timelines(workflow, jobs, workers)
    trace_events = trace_timeline(traces)
    causality_chain = merged_timeline_events(trace_events, timelines["recent"], events)
    recovery = workflow_recovery_summary(workflow, jobs, workers, missing_worker_ids)
    rollup = incident_rollup(
        workflow,
        recovery=recovery,
        incident_events=events,
        causality_chain=causality_chain,
    )

    return {
        "workflow_id": workflow.workflow_id,
        "workflow_status": workflow.status,
        "correlation_ids": correlation_ids,
        "current_step": {
            "step_id": current_step(workflow).step_id,
            "step_type": current_step(workflow).step_type,
            "status": current_step(workflow).status,
        },
        "failure": workflow_failure_view(workflow),
        "recovery": recovery,
        "approvals": approvals,
        "jobs": jobs,
        "workers": workers,
        "missing_worker_ids": missing_worker_ids,
        "traces": traces,
        "timelines": {
            **timelines,
            "traces": trace_events,
            "causality_chain": causality_chain,
        },
        "queue_health": queue_health_summary(),
        "worker_health": worker_health_summary(),
        "incident": {
            **incident_traces,
            "approval_count": len(approvals),
            "job_count": len(jobs),
            "worker_count": len(workers),
            "classifications": classifications,
            "recent_events": events[:10],
            "recent_timeline": timelines["recent"][:10],
            "causality_chain": causality_chain[:10],
            "rollup": rollup,
        },
    }


def workflow_incident_summary_view(workflow_id: str, *, trace_limit: int = 20) -> dict:
    incident_view = workflow_incident_view(workflow_id, trace_limit=trace_limit)
    incident = incident_view["incident"]
    queue_health = incident_view["queue_health"]
    worker_health = incident_view["worker_health"]

    return {
        "workflow_id": incident_view["workflow_id"],
        "workflow_status": incident_view["workflow_status"],
        "current_step": dict(incident_view["current_step"]),
        "failure": incident_view["failure"],
        "recovery": dict(incident_view["recovery"]),
        "correlation_ids": dict(incident_view["correlation_ids"]),
        "incident": {
            "trace_count": incident["trace_count"],
            "error_trace_count": incident["error_trace_count"],
            "classifications": dict(incident["classifications"]),
            "recent_events": [dict(event) for event in incident["recent_events"]],
            "causality_chain": [dict(event) for event in incident["causality_chain"]],
            "rollup": dict(incident["rollup"]),
        },
        "queue_health": {
            "total_jobs": queue_health["total_jobs"],
            "retry_pending_count": queue_health["retry_pending_count"],
            "dead_letter_count": queue_health["dead_letter_count"],
            "health": {
                "retry_backlog_count": queue_health["health"]["retry_backlog_count"],
                "failed_count": queue_health["health"]["failed_count"],
                "dead_letter_count": queue_health["health"]["dead_letter_count"],
                "expired_running_count": queue_health["health"]["expired_running_count"],
                "recent_events": [dict(event) for event in queue_health["health"]["trends"]["recent_events"]],
            },
        },
        "worker_health": {
            "total_workers": worker_health["total_workers"],
            "counts": dict(worker_health["counts"]),
            "expired_worker_ids": list(worker_health["expired_worker_ids"]),
            "orphaned_worker_ids": list(worker_health["orphaned_worker_ids"]),
            "trends": {
                "expired_workers_last_hour": worker_health["trends"]["expired_workers_last_hour"],
                "orphaned_workers_last_hour": worker_health["trends"]["orphaned_workers_last_hour"],
                "recent_events": [dict(event) for event in worker_health["trends"]["recent_events"]],
            },
        },
    }


def reclaim_related_expired_jobs(jobs: list[dict]) -> list[str]:
    reclaimed_job_ids = []
    for job in jobs:
        if not job_lease_expired(job):
            continue

        reclaimed = requeue_job(
            job["job_id"],
            reason=f"Lease expired for worker `{job.get('worker_id')}`",
        )
        reclaimed_job_ids.append(reclaimed["job_id"])

        worker_id = job.get("worker_id")
        if worker_id is None:
            continue
        try:
            worker = load_worker(worker_id)
        except FileNotFoundError:
            continue
        if worker.get("current_job_id") == job["job_id"]:
            update_worker(
                worker_id,
                status="idle",
                current_job_id=None,
            )

    return reclaimed_job_ids


def recover_workflow(
    workflow_id: str,
    *,
    reclaim_expired_jobs: bool = False,
    reschedule_failed_jobs: bool = False,
    reschedule_dead_letter_jobs: bool = False,
    limit: int | None = None,
) -> dict:
    workflow = load_workflow(workflow_id)
    if not any([reclaim_expired_jobs, reschedule_failed_jobs, reschedule_dead_letter_jobs]):
        raise ValueError("Workflow recovery requires at least one explicit action")
    if limit is not None and (not isinstance(limit, int) or limit <= 0):
        raise ValueError("Workflow recovery `limit` must be a positive integer")

    jobs = related_jobs_for_workflow(workflow)
    reclaimed_job_ids = reclaim_related_expired_jobs(jobs) if reclaim_expired_jobs else []

    rescheduled_job_ids = []
    statuses = set()
    if reschedule_failed_jobs:
        statuses.add("failed")
    if reschedule_dead_letter_jobs:
        statuses.add("dead_letter")
    if statuses:
        candidates = [job for job in jobs if job["status"] in statuses]
        if limit is not None:
            candidates = candidates[:limit]
        for job in candidates:
            rescheduled = reschedule_job(job["job_id"], delay_seconds=0)
            rescheduled_job_ids.append(rescheduled["job_id"])

    refreshed_jobs = related_jobs_for_workflow(workflow)
    workers, missing_worker_ids = related_workers_for_jobs(refreshed_jobs)
    recovery = workflow_recovery_summary(workflow, refreshed_jobs, workers, missing_worker_ids)

    return {
        "workflow_id": workflow_id,
        "actions_requested": {
            "reclaim_expired_jobs": reclaim_expired_jobs,
            "reschedule_failed_jobs": reschedule_failed_jobs,
            "reschedule_dead_letter_jobs": reschedule_dead_letter_jobs,
            "limit": limit,
        },
        "reclaimed_job_ids": reclaimed_job_ids,
        "reclaimed_count": len(reclaimed_job_ids),
        "rescheduled_job_ids": rescheduled_job_ids,
        "rescheduled_count": len(rescheduled_job_ids),
        "recovery": recovery,
        "jobs": refreshed_jobs,
        "workers": workers,
        "missing_worker_ids": missing_worker_ids,
    }


def workflow_actions(workflow, approvals: list[dict]) -> dict:
    step = current_step(workflow)
    pending_approvals = [approval for approval in approvals if approval["status"] == "pending"]
    jobs = related_jobs_for_workflow(workflow)
    workers, missing_worker_ids = related_workers_for_jobs(jobs)
    recovery = workflow_recovery_summary(workflow, jobs, workers, missing_worker_ids)

    return {
        "resume": {
            "available": workflow.status == "waiting",
            "path": f"/workflows/{workflow.workflow_id}/resume",
            "step_type": step.step_type,
        },
        "resume_safe": {
            "available": workflow.status == "waiting" and step.step_type in {"approval_wait", "retry_wait"},
            "path": f"/workflows/{workflow.workflow_id}/resume-safe",
            "step_type": step.step_type,
        },
        "replay": {
            "available": workflow.status == "failed" and bool(workflow.request),
            "path": f"/workflows/{workflow.workflow_id}/replay",
        },
        "spawn_subrun": {
            "available": can_spawn_child_workflow(workflow),
            "path": f"/workflows/{workflow.workflow_id}/subruns",
            "remaining_children": max(
                workflow.subrun_policy["max_children"] - len(workflow.child_workflow_ids),
                0,
            ),
            "max_depth": workflow.subrun_policy["max_depth"],
        },
        "approvals": [
            {
                "approval_id": approval["approval_id"],
                "approve_path": f"/approvals/{approval['approval_id']}/approve",
                "deny_path": f"/approvals/{approval['approval_id']}/deny",
                "abort_path": f"/approvals/{approval['approval_id']}/abort",
            }
            for approval in pending_approvals
        ],
        "artifacts": [
            {
                "artifact_id": artifact["artifact_id"],
                "path": f"/artifacts/{artifact['artifact_id']}",
            }
            for artifact in workflow.artifacts
        ],
        "memories": [
            {
                "memory_id": memory["memory_id"],
                "artifact_id": memory.get("artifact_id"),
            }
            for memory in workflow.memories
        ],
        "child_workflows": [
            {
                "workflow_id": child_workflow_id,
                "path": f"/workflows/{child_workflow_id}",
            }
            for child_workflow_id in workflow.child_workflow_ids
        ],
        "recover": {
            "available": recovery["has_recovery_actions"],
            "path": f"/workflows/{workflow.workflow_id}/recover",
            "expired_running_job_ids": recovery["expired_running_job_ids"],
            "failed_job_ids": recovery["failed_job_ids"],
            "dead_letter_job_ids": recovery["dead_letter_job_ids"],
        },
    }


def workflow_control_view(workflow_id: str) -> dict:
    workflow = load_workflow(workflow_id)
    snapshot = workflow_snapshot(workflow)
    approvals = [approval_summary(approval) for approval in list_approvals_for_workflow(workflow_id)]
    artifacts = [
        artifact_summary(artifact)
        for artifact in list_artifacts_for_workflow(workflow_id)
    ]
    memories = [memory_summary(memory) for memory in workflow.memories]
    jobs = related_jobs_for_workflow(workflow)
    workers, missing_worker_ids = related_workers_for_jobs(jobs)
    children, missing_child_workflow_ids = child_workflow_views(workflow)
    child_summary = child_workflow_summary(workflow, children, missing_child_workflow_ids)
    recovery = workflow_recovery_summary(workflow, jobs, workers, missing_worker_ids)
    traces = related_trace_summaries_for_workflow(workflow, limit=10)
    incident = incident_trace_summary(traces)
    incident_events = workflow_incident_events(workflow, jobs, workers, traces)
    correlation_ids = workflow_correlation_ids(workflow, approvals, jobs, workers, traces)
    timelines = workflow_transition_timelines(workflow, jobs, workers)
    trace_events = trace_timeline(traces)
    causality_chain = merged_timeline_events(trace_events, timelines["recent"], incident_events)
    rollup = incident_rollup(
        workflow,
        recovery=recovery,
        incident_events=incident_events,
        causality_chain=causality_chain,
    )
    step = current_step(workflow)

    return {
        **snapshot,
        "correlation_ids": correlation_ids,
        "current_step": {
            "step_id": step.step_id,
            "step_type": step.step_type,
            "status": step.status,
            "details": dict(step.details),
            "error": dict(step.error) if step.error is not None else None,
        },
        "approvals": approvals,
        "artifacts": artifacts,
        "memories": memories,
        "shared_memories": [dict(memory) for memory in workflow.shared_memories],
        "jobs": jobs,
        "workers": workers,
        "missing_worker_ids": missing_worker_ids,
        "recovery": recovery,
        "timelines": {
            **timelines,
            "traces": trace_events,
            "causality_chain": causality_chain,
        },
        "incident": {
            **incident,
            "classifications": incident_classification_summary(incident_events),
            "recent_events": incident_events[:5],
            "recent_timeline": timelines["recent"][:5],
            "causality_chain": causality_chain[:5],
            "rollup": rollup,
        },
        "child_workflows": children,
        "child_summary": child_summary,
        "failure": workflow_failure_view(workflow),
        "missing_child_workflow_ids": missing_child_workflow_ids,
        "actions": workflow_actions(workflow, approvals),
    }


def queue_health_view() -> dict:
    return queue_health_summary()


def worker_health_view() -> dict:
    return worker_health_summary()


def load_related_workflows_for_session(session) -> tuple[list, list[str]]:
    workflows = []
    missing = []
    for workflow_id in session.workflow_ids:
        try:
            workflows.append(load_workflow(workflow_id))
        except FileNotFoundError:
            missing.append(workflow_id)
    workflows.sort(key=lambda workflow: workflow.updated_at, reverse=True)
    return workflows, missing


def session_memory_continuity(session, *, limit: int = 10) -> dict:
    scope = dict(session.memory_scope)
    scope_kind = scope["kind"]
    scope_value = scope.get("value")
    continuity = {
        "scope": scope,
        "recent": [],
        "workflow_recent": [],
        "message_memory_gap": len(session.messages) == 0,
    }

    if scope_kind == "global":
        scoped = list_memories(scope_kind="global", limit=limit)
    elif scope_kind == "agent":
        scoped = list_memories(scope_kind="agent", agent=scope_value, limit=limit)
    elif scope_kind == "workflow":
        scoped = list_memories(scope_kind="workflow", workflow_id=scope_value, limit=limit) if scope_value else []
    else:
        scoped = list_memories(scope_kind="run", run_id=scope_value, limit=limit) if scope_value else []

    continuity["recent"] = [memory_summary(memory) for memory in scoped]

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

    continuity["workflow_recent"] = workflow_memories
    continuity["message_memory_gap"] = bool(session.messages) and not continuity["recent"] and not continuity["workflow_recent"]
    return continuity


def session_workflow_rollup(workflows: list, missing_workflow_ids: list[str]) -> dict:
    counts = {
        "running": 0,
        "waiting": 0,
        "succeeded": 0,
        "failed": 0,
        "missing": len(missing_workflow_ids),
    }
    latest = None
    failures = []
    for workflow in workflows:
        counts[workflow.status] = counts.get(workflow.status, 0) + 1
        if latest is None or workflow.updated_at > latest.updated_at:
            latest = workflow
        failure = workflow_failure_view(workflow)
        if failure is not None:
            failures.append(
                {
                    "workflow_id": workflow.workflow_id,
                    "agent": workflow.agent,
                    "failure_classification": failure["failure_classification"],
                    "error": dict(failure["error"]) if failure["error"] is not None else None,
                    "path": f"/workflows/{workflow.workflow_id}",
                }
            )

    return {
        "counts": counts,
        "latest_workflow_id": latest.workflow_id if latest is not None else None,
        "latest_status": latest.status if latest is not None else None,
        "failures": failures[:10],
        "missing_workflow_ids": list(missing_workflow_ids),
    }


def session_message_rollup(session) -> dict:
    counts = {
        "user": 0,
        "assistant": 0,
        "system": 0,
        "submitted": 0,
        "completed": 0,
        "waiting": 0,
        "errored": 0,
    }
    latest_message = None
    for message in session.messages:
        counts[message.role] = counts.get(message.role, 0) + 1
        counts[message.status] = counts.get(message.status, 0) + 1
        latest_message = message

    return {
        "message_count": len(session.messages),
        "counts": counts,
        "latest_message": (
            {
                "message_id": latest_message.message_id,
                "role": latest_message.role,
                "status": latest_message.status,
                "created_at": latest_message.created_at,
                "content_preview": truncate_text(latest_message.content, limit=100),
                "workflow_id": latest_message.workflow_id,
                "run_id": latest_message.run_id,
            }
            if latest_message is not None
            else None
        ),
    }


def session_current_workflow_view(session, workflow_views: list[dict]) -> dict | None:
    if not workflow_views:
        return None

    current_workflow_id = session.current_workflow_id
    selected = None
    if current_workflow_id is not None:
        for view in workflow_views:
            if view["workflow_id"] == current_workflow_id:
                selected = view
                break
    if selected is None:
        selected = workflow_views[0]

    pending_approvals = [approval for approval in selected.get("approvals", []) if approval.get("status") == "pending"]
    return {
        "workflow_id": selected["workflow_id"],
        "status": selected["status"],
        "agent": selected["agent"],
        "path": f"/workflows/{selected['workflow_id']}",
        "current_step": dict(selected["current_step"]),
        "incident_rollup": dict(selected["incident"]["rollup"]),
        "pending_approval_count": len(pending_approvals),
        "actions": dict(selected["actions"]),
        "recent_timeline": [dict(event) for event in selected["timelines"]["causality_chain"][:10]],
    }


def session_activity_timeline(session, current_workflow: dict | None, latest_incident: dict | None) -> list[dict]:
    events = []
    for message in session.messages:
        events.append(
            {
                "source": "session",
                "event_type": "session_message",
                "timestamp": message.created_at,
                "message_id": message.message_id,
                "role": message.role,
                "status": message.status,
                "content_preview": truncate_text(message.content, limit=120),
                "workflow_id": message.workflow_id,
                "run_id": message.run_id,
                "job_id": message.job_id,
            }
        )

    if current_workflow is not None:
        for event in current_workflow.get("recent_timeline", []):
            enriched = dict(event)
            enriched.setdefault("source", "workflow")
            events.append(enriched)

    if latest_incident is not None:
        for event in latest_incident["incident"].get("recent_events", []):
            enriched = dict(event)
            enriched.setdefault("source", "incident")
            events.append(enriched)

    events.sort(key=event_sort_key, reverse=True)
    return events[:15]


def operator_dashboard_view(*, session_limit: int = 20) -> dict:
    sessions = list_sessions(limit=session_limit)
    status_counts = {}
    for session in sessions:
        status = session["status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "sessions": sessions,
        "session_rollup": {
            "total_sessions": len(sessions),
            "counts": status_counts,
            "latest_session_id": sessions[0]["session_id"] if sessions else None,
            "waiting_session_ids": [session["session_id"] for session in sessions if session["status"] == "waiting"],
            "errored_session_ids": [session["session_id"] for session in sessions if session["status"] == "errored"],
        },
        "queue_health": queue_health_view(),
        "worker_health": worker_health_view(),
    }


def session_control_view(session_id: str) -> dict:
    session = load_session(session_id)
    workflows, missing_workflow_ids = load_related_workflows_for_session(session)
    workflow_views = [workflow_control_view(workflow.workflow_id) for workflow in workflows[:5]]
    latest_workflow = workflows[0] if workflows else None
    latest_incident = (
        workflow_incident_summary_view(latest_workflow.workflow_id)
        if latest_workflow is not None
        else None
    )
    continuity = session_memory_continuity(session)
    rollup = session_workflow_rollup(workflows, missing_workflow_ids)
    message_rollup = session_message_rollup(session)
    current_workflow = session_current_workflow_view(session, workflow_views)
    recent_activity = session_activity_timeline(session, current_workflow, latest_incident)

    return {
        **session_snapshot(session),
        "session_rollup": message_rollup,
        "workflow_rollup": rollup,
        "related_workflows": [
            {
                "workflow_id": view["workflow_id"],
                "status": view["status"],
                "agent": view["agent"],
                "current_step": dict(view["current_step"]),
                "path": f"/workflows/{view['workflow_id']}",
                "incident_rollup": dict(view["incident"]["rollup"]),
            }
            for view in workflow_views
        ],
        "current_workflow": current_workflow,
        "latest_incident": latest_incident,
        "continuity": continuity,
        "activity": {
            "recent_timeline": recent_activity,
        },
        "actions": {
            "append_message_path": f"/sessions/{session.session_id}/messages",
            "current_workflow_path": (
                f"/workflows/{session.current_workflow_id}"
                if session.current_workflow_id is not None
                else None
            ),
            "latest_incident_path": (
                f"/incidents/workflows/{latest_workflow.workflow_id}/summary"
                if latest_workflow is not None
                else None
            ),
        },
    }
