import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from runtime.queue import (
    cancel_job,
    job_lease_expired,
    list_jobs,
    load_job,
    normalize_optional_limit,
    ready_jobs,
    record_job_failure,
    requeue_job,
    update_job,
)
from runtime.storage import WORKER_DIR
from runtime.state import load_state_payload, write_state_payload
from runtime.workflow_runner import resume_workflow, start_child_workflow, start_workflow

DEFAULT_LEASE_SECONDS = 30
WORKER_STATE_SCHEMA = "worker.v1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_timestamp(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


def duration_seconds_since(timestamp: str | None) -> int | None:
    if timestamp is None:
        return None
    delta = utc_now() - parse_timestamp(timestamp)
    return max(int(delta.total_seconds()), 0)


def occurred_within_seconds(timestamp: str | None, *, seconds: int) -> bool:
    if timestamp is None:
        return False
    return duration_seconds_since(timestamp) <= seconds


def normalize_transition_history(value: Any, *, field_name: str = "transition_history") -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Worker `{field_name}` must be a list")

    normalized = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError(f"Worker `{field_name}` entries must be objects")
        normalized.append(dict(entry))
    return normalized


def worker_transition_changed_fields(current: dict[str, Any], updated: dict[str, Any]) -> dict[str, dict[str, Any]]:
    changed_fields = {}
    for field in ["status", "current_job_id", "last_heartbeat_at", "lease_expires_at"]:
        if current.get(field) != updated.get(field):
            changed_fields[field] = {
                "from": current.get(field),
                "to": updated.get(field),
            }
    return changed_fields


def classify_worker_transition_event(current: dict[str, Any], updated: dict[str, Any]) -> str:
    if current.get("current_job_id") != updated.get("current_job_id"):
        if updated.get("current_job_id") is not None:
            return "job_assigned"
        return "job_released"
    if current.get("status") != updated.get("status"):
        return "status_changed"
    if current.get("last_heartbeat_at") != updated.get("last_heartbeat_at"):
        return "heartbeat"
    return "lease_updated"


def build_worker_transition_history(
    previous: dict[str, Any] | None,
    updated: dict[str, Any],
    *,
    transition_reason: str | None = None,
    transition_details: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    history = normalize_transition_history(
        previous.get("transition_history") if previous is not None else updated.get("transition_history")
    )
    timestamp = updated["updated_at"]

    if previous is None:
        history.append(
            {
                "event_type": "created",
                "timestamp": timestamp,
                "status": updated["status"],
                "lease_seconds": updated["lease_seconds"],
            }
        )
        return history

    changed_fields = worker_transition_changed_fields(previous, updated)
    if not changed_fields:
        return history

    history.append(
        {
            "event_type": classify_worker_transition_event(previous, updated),
            "timestamp": timestamp,
            "from_status": previous.get("status"),
            "to_status": updated.get("status"),
            "current_job_id": updated.get("current_job_id"),
            "reason": transition_reason,
            "changed_fields": changed_fields,
            "details": dict(transition_details or {}),
        }
    )
    return history


def worker_path(worker_id: str) -> Path:
    return WORKER_DIR / f"{worker_id}.json"


def ensure_worker_dir() -> None:
    WORKER_DIR.mkdir(exist_ok=True)


def worker_summary(worker: dict[str, Any]) -> dict[str, Any]:
    lease_expired = worker_lease_expired(worker)
    return {
        "worker_id": worker["worker_id"],
        "name": worker["name"],
        "status": "expired" if lease_expired and worker.get("current_job_id") is not None else worker["status"],
        "lease_seconds": worker["lease_seconds"],
        "last_heartbeat_at": worker["last_heartbeat_at"],
        "lease_expires_at": worker["lease_expires_at"],
        "lease_expired": lease_expired,
        "current_job_id": worker.get("current_job_id"),
        "transition_history": normalize_transition_history(worker.get("transition_history")),
        "created_at": worker["created_at"],
        "updated_at": worker["updated_at"],
    }


def write_worker(worker: dict[str, Any]) -> dict[str, Any]:
    ensure_worker_dir()
    path = worker_path(worker["worker_id"])
    summary = worker_summary(worker)
    previous = load_state_payload(path, schema=WORKER_STATE_SCHEMA) if path.is_file() else None
    summary["transition_history"] = build_worker_transition_history(previous, summary)
    return write_state_payload(path, summary, schema=WORKER_STATE_SCHEMA)


def register_worker(*, name: str | None = None, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> dict[str, Any]:
    if not isinstance(lease_seconds, int) or lease_seconds <= 0:
        raise ValueError("Worker `lease_seconds` must be a positive integer")

    timestamp = utc_now()
    worker = {
        "worker_id": str(uuid.uuid4()),
        "name": name or "worker",
        "status": "idle",
        "lease_seconds": lease_seconds,
        "last_heartbeat_at": timestamp.isoformat(),
        "lease_expires_at": (timestamp + timedelta(seconds=lease_seconds)).isoformat(),
        "current_job_id": None,
        "transition_history": [],
        "created_at": timestamp.isoformat(),
        "updated_at": timestamp.isoformat(),
    }
    return write_worker(worker)


def load_worker(worker_id: str) -> dict[str, Any]:
    path = worker_path(worker_id)
    if not path.is_file():
        raise FileNotFoundError(f"Worker not found: {worker_id}")

    worker = load_state_payload(path, schema=WORKER_STATE_SCHEMA)
    worker["transition_history"] = normalize_transition_history(worker.get("transition_history"))
    return worker


def update_worker(
    worker_id: str,
    *,
    transition_reason: str | None = None,
    transition_details: dict[str, Any] | None = None,
    **changes: Any,
) -> dict[str, Any]:
    worker = load_worker(worker_id)
    updated = {
        **worker,
        **changes,
        "updated_at": utc_now_iso(),
    }
    summary = worker_summary(updated)
    summary["transition_history"] = build_worker_transition_history(
        worker,
        summary,
        transition_reason=transition_reason,
        transition_details=transition_details,
    )
    ensure_worker_dir()
    return write_state_payload(worker_path(worker_id), summary, schema=WORKER_STATE_SCHEMA)


def worker_lease_expired(worker: dict[str, Any]) -> bool:
    lease_expires_at = worker.get("lease_expires_at")
    if not lease_expires_at:
        return False
    return parse_timestamp(lease_expires_at) <= utc_now()


def heartbeat_worker(worker_id: str) -> dict[str, Any]:
    worker = load_worker(worker_id)
    if worker_lease_expired(worker) and worker.get("current_job_id") is not None:
        raise ValueError(
            f"Worker `{worker_id}` lease expired while holding job `{worker['current_job_id']}`"
        )
    lease_seconds = worker["lease_seconds"]
    timestamp = utc_now()
    return update_worker(
        worker_id,
        last_heartbeat_at=timestamp.isoformat(),
        lease_expires_at=(timestamp + timedelta(seconds=lease_seconds)).isoformat(),
        transition_reason="heartbeat",
    )


def list_workers() -> list[dict[str, Any]]:
    if not WORKER_DIR.is_dir():
        return []

    workers = []
    for path in sorted(WORKER_DIR.glob("*.json")):
        current = load_state_payload(path, schema=WORKER_STATE_SCHEMA)
        current["transition_history"] = normalize_transition_history(current.get("transition_history"))
        workers.append(current)
    return workers


def worker_reset_snapshot(
    worker: dict[str, Any],
    *,
    reason: str,
    requeued_job_ids: list[str],
    forced: bool,
) -> dict[str, Any]:
    return {
        "worker": worker,
        "reason": reason,
        "forced": forced,
        "requeued_job_ids": requeued_job_ids,
        "requeued_count": len(requeued_job_ids),
    }


def reset_worker(
    worker_id: str,
    *,
    reason: str = "operator",
    force: bool = False,
    requeue_running_job: bool = False,
) -> dict[str, Any]:
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Worker reset `reason` must be a non-empty string")

    worker = load_worker(worker_id)
    current_job_id = worker.get("current_job_id")
    requeued_job_ids = []

    if current_job_id is not None:
        try:
            job = load_job(current_job_id)
        except FileNotFoundError:
            if not force:
                force = True
        else:
            owns_running_job = job["status"] == "running" and job.get("worker_id") == worker_id
            if owns_running_job:
                if requeue_running_job:
                    requeued = requeue_job(current_job_id, reason=f"Worker reset: {reason.strip()}")
                    requeued_job_ids.append(requeued["job_id"])
                elif not force:
                    raise ValueError(
                        f"Worker `{worker_id}` is actively holding job `{current_job_id}`; "
                        "pass `requeue_running_job` or `force` to reset"
                    )
            elif not force and worker.get("status") != "idle":
                raise ValueError(
                    f"Worker `{worker_id}` is not idle and cannot be reset without `force`"
                )

    timestamp = utc_now()
    repaired = update_worker(
        worker_id,
        status="idle",
        current_job_id=None,
        last_heartbeat_at=timestamp.isoformat(),
        lease_expires_at=(timestamp + timedelta(seconds=worker["lease_seconds"])).isoformat(),
        transition_reason=reason.strip(),
        transition_details={"forced": force, "requeued_job_ids": requeued_job_ids},
    )
    return worker_reset_snapshot(
        repaired,
        reason=reason.strip(),
        requeued_job_ids=requeued_job_ids,
        forced=force,
    )


def repair_orphaned_workers(*, limit: int | None = None) -> dict[str, Any]:
    limit = normalize_optional_limit(limit, field_name="repair_orphans.limit")

    repaired_workers = []
    for current in list_workers():
        reason = None
        current_job_id = current.get("current_job_id")
        if current_job_id is None:
            if current.get("status") != "idle":
                reason = "Worker marked busy without a current job"
        else:
            try:
                job = load_job(current_job_id)
            except FileNotFoundError:
                reason = f"Worker references missing job `{current_job_id}`"
            else:
                if job["status"] != "running":
                    reason = (
                        f"Worker references job `{current_job_id}` in terminal/non-running status "
                        f"`{job['status']}`"
                    )
                elif job.get("worker_id") != current["worker_id"]:
                    reason = (
                        f"Worker references job `{current_job_id}` claimed by "
                        f"`{job.get('worker_id')}`"
                    )

        if reason is None:
            continue

        repaired_workers.append(
            reset_worker(
                current["worker_id"],
                reason=reason,
                force=True,
            )
        )
        if limit is not None and len(repaired_workers) >= limit:
            break

    return {
        "repaired_workers": repaired_workers,
        "repaired_worker_ids": [entry["worker"]["worker_id"] for entry in repaired_workers],
        "repaired_count": len(repaired_workers),
    }


def worker_health_summary() -> dict[str, Any]:
    workers = [worker_summary(current) for current in list_workers()]
    counts = {"idle": 0, "busy": 0, "expired": 0}
    orphaned_worker_ids = []
    busy_worker_ids = []
    expired_worker_ids = []
    heartbeat_ages = []
    lease_remaining_seconds = []
    heartbeat_age_buckets = {
        "under_30s": 0,
        "30_to_300s": 0,
        "over_300s": 0,
    }
    lifecycle_counts = {
        "heartbeat": 0,
        "job_assigned": 0,
        "job_released": 0,
        "status_changed": 0,
        "lease_updated": 0,
    }
    recent_lifecycle_events = []
    recent_events = []

    for current in workers:
        status = current["status"]
        counts[status] = counts.get(status, 0) + 1
        if current.get("current_job_id") is not None:
            busy_worker_ids.append(current["worker_id"])
        if current.get("lease_expired"):
            expired_worker_ids.append(current["worker_id"])
        heartbeat_age = duration_seconds_since(current.get("last_heartbeat_at"))
        if heartbeat_age is not None:
            heartbeat_ages.append(heartbeat_age)
            if heartbeat_age < 30:
                heartbeat_age_buckets["under_30s"] += 1
            elif heartbeat_age <= 300:
                heartbeat_age_buckets["30_to_300s"] += 1
            else:
                heartbeat_age_buckets["over_300s"] += 1

        lease_expires_at = current.get("lease_expires_at")
        if lease_expires_at is not None:
            remaining = int((parse_timestamp(lease_expires_at) - utc_now()).total_seconds())
            lease_remaining_seconds.append(max(remaining, 0))

        current_job_id = current.get("current_job_id")
        for entry in current.get("transition_history", []):
            event_type = entry.get("event_type")
            changed_fields = entry.get("changed_fields") or {}
            if event_type in lifecycle_counts:
                lifecycle_counts[event_type] += 1
                recent_lifecycle_events.append(
                    {
                        "event_type": event_type,
                        "worker_id": current["worker_id"],
                        "timestamp": entry.get("timestamp"),
                        "reason": entry.get("reason"),
                        "current_job_id": entry.get("current_job_id"),
                    }
                )
            if "last_heartbeat_at" in changed_fields and event_type != "heartbeat":
                lifecycle_counts["heartbeat"] += 1
                recent_lifecycle_events.append(
                    {
                        "event_type": "heartbeat",
                        "worker_id": current["worker_id"],
                        "timestamp": entry.get("timestamp"),
                        "reason": entry.get("reason"),
                        "current_job_id": entry.get("current_job_id"),
                    }
                )
        if current_job_id is None and current["status"] != "idle":
            orphaned_worker_ids.append(current["worker_id"])
            recent_events.append(
                {
                    "event_type": "orphaned_worker",
                    "worker_id": current["worker_id"],
                    "timestamp": current["updated_at"],
                    "message": "Worker marked busy without current job",
                }
            )
            continue
        if current_job_id is None:
            if current.get("lease_expired"):
                recent_events.append(
                    {
                        "event_type": "expired_worker",
                        "worker_id": current["worker_id"],
                        "timestamp": current.get("lease_expires_at") or current["updated_at"],
                        "message": "Worker lease expired while idle",
                    }
                )
            continue
        try:
            job = load_job(current_job_id)
        except FileNotFoundError:
            orphaned_worker_ids.append(current["worker_id"])
            recent_events.append(
                {
                    "event_type": "orphaned_worker",
                    "worker_id": current["worker_id"],
                    "timestamp": current["updated_at"],
                    "message": f"Worker references missing job `{current_job_id}`",
                }
            )
            continue
        if job["status"] != "running" or job.get("worker_id") != current["worker_id"]:
            orphaned_worker_ids.append(current["worker_id"])
            recent_events.append(
                {
                    "event_type": "orphaned_worker",
                    "worker_id": current["worker_id"],
                    "timestamp": current["updated_at"],
                    "message": f"Worker references inconsistent job `{current_job_id}`",
                }
            )
        elif current.get("lease_expired"):
            recent_events.append(
                {
                    "event_type": "expired_worker",
                    "worker_id": current["worker_id"],
                    "timestamp": current.get("lease_expires_at") or current["updated_at"],
                    "message": f"Worker lease expired while holding job `{current_job_id}`",
                }
            )

    recent_events.sort(key=lambda event: (event["timestamp"] or "", event["worker_id"]), reverse=True)
    recent_lifecycle_events.sort(key=lambda event: (event["timestamp"] or "", event["worker_id"]), reverse=True)

    return {
        "counts": counts,
        "total_workers": len(workers),
        "busy_worker_ids": busy_worker_ids,
        "expired_worker_ids": expired_worker_ids,
        "orphaned_worker_ids": orphaned_worker_ids,
        "max_heartbeat_age_seconds": max(heartbeat_ages, default=None),
        "min_lease_remaining_seconds": min(lease_remaining_seconds, default=None),
        "lifecycle": {
            "counts": lifecycle_counts,
            "recent_events": recent_lifecycle_events[:10],
        },
        "trends": {
            "recently_updated_workers_last_hour": sum(
                1 for current in workers if occurred_within_seconds(current.get("updated_at"), seconds=3600)
            ),
            "expired_workers_last_hour": sum(
                1 for current in workers if current.get("lease_expired") and occurred_within_seconds(current.get("updated_at"), seconds=3600)
            ),
            "orphaned_workers_last_hour": sum(
                1 for worker_id in orphaned_worker_ids
                if occurred_within_seconds(load_worker(worker_id).get("updated_at"), seconds=3600)
            ),
            "heartbeat_age_buckets": heartbeat_age_buckets,
            "recent_events": recent_events[:5],
        },
    }


def reclaim_expired_leases() -> dict[str, Any]:
    reclaimed_job_ids = []
    for job in list_jobs(status="running"):
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

    return {
        "reclaimed_job_ids": reclaimed_job_ids,
        "reclaimed_count": len(reclaimed_job_ids),
    }


def claim_next_job(worker_id: str) -> dict[str, Any] | None:
    reclaim_expired_leases()
    worker = load_worker(worker_id)
    if worker_lease_expired(worker) and worker.get("current_job_id") is not None:
        raise ValueError(
            f"Worker `{worker_id}` lease expired while holding job `{worker['current_job_id']}`"
        )
    if worker_lease_expired(worker):
        worker = heartbeat_worker(worker_id)
    else:
        worker = heartbeat_worker(worker_id)
    if worker.get("current_job_id") is not None:
        raise ValueError(f"Worker `{worker_id}` is already assigned to job `{worker['current_job_id']}`")

    jobs = ready_jobs()
    if not jobs:
        return None

    job = jobs[0]
    timestamp = utc_now()
    leased_job = update_job(
        job["job_id"],
        status="running",
        worker_id=worker_id,
        claimed_at=timestamp.isoformat(),
        lease_expires_at=(timestamp + timedelta(seconds=worker["lease_seconds"])).isoformat(),
        transition_reason=f"claimed_by_worker:{worker_id}",
    )
    update_worker(
        worker_id,
        status="busy",
        current_job_id=job["job_id"],
        last_heartbeat_at=timestamp.isoformat(),
        lease_expires_at=(timestamp + timedelta(seconds=worker["lease_seconds"])).isoformat(),
        transition_reason=f"claimed_job:{job['job_id']}",
    )
    return leased_job


def dispatch_job(job: dict[str, Any]) -> dict[str, Any]:
    payload = job["payload"]
    if job["job_type"] == "workflow_start":
        return start_workflow(
            user_input=payload.get("input", ""),
            agent_name=payload.get("agent", "default"),
            tool_name=payload.get("tool"),
            tool_args=payload.get("tool_args"),
            approval_id=payload.get("approval_id"),
            job_id=job["job_id"],
            worker_id=job.get("worker_id"),
        )
    if job["job_type"] == "workflow_resume":
        return resume_workflow(
            payload["workflow_id"],
            job_id=job["job_id"],
            worker_id=job.get("worker_id"),
        )
    if job["job_type"] == "workflow_subrun":
        return start_child_workflow(
            payload["workflow_id"],
            user_input=payload.get("input", ""),
            agent_name=payload.get("agent", "default"),
            tool_name=payload.get("tool"),
            tool_args=payload.get("tool_args"),
            role=payload.get("role"),
            allowed_capabilities=payload.get("allowed_capabilities"),
            allowed_tools=payload.get("allowed_tools"),
            task_intent=payload.get("task_intent"),
            expected_output=payload.get("expected_output"),
            completion_criteria=payload.get("completion_criteria"),
            shared_memory_ids=payload.get("shared_memory_ids"),
            job_id=job["job_id"],
            worker_id=job.get("worker_id"),
        )
    raise ValueError(f"Unsupported job type: {job['job_type']}")


def complete_job(job_id: str, *, result: dict[str, Any]) -> dict[str, Any]:
    return update_job(
        job_id,
        status="completed",
        result=result,
        error=None,
        lease_expires_at=None,
        transition_reason="job_completed",
    )


def fail_job(job_id: str, *, exc: Exception) -> dict[str, Any]:
    return record_job_failure(job_id, exc=exc)


def release_worker(worker_id: str) -> dict[str, Any]:
    return update_worker(
        worker_id,
        status="idle",
        current_job_id=None,
        transition_reason="job_released",
    )


def cancel_job_execution(job_id: str, *, reason: str = "operator") -> dict[str, Any]:
    job = load_job(job_id)
    canceled = cancel_job(job_id, reason=reason)

    worker_id = job.get("worker_id")
    if worker_id is not None:
        try:
            worker = load_worker(worker_id)
        except FileNotFoundError:
            return canceled
        if worker.get("current_job_id") == job_id:
            release_worker(worker_id)

    return canceled


def run_claimed_job(worker_id: str, job_id: str) -> dict[str, Any]:
    worker = load_worker(worker_id)
    if worker_lease_expired(worker):
        raise ValueError(f"Worker `{worker_id}` lease expired before running job `{job_id}`")
    worker = heartbeat_worker(worker_id)
    job = load_job(job_id)
    if job["status"] == "canceled":
        if worker.get("current_job_id") == job_id:
            release_worker(worker_id)
        elif worker.get("status") != "idle":
            release_worker(worker_id)
        return job
    if worker.get("current_job_id") != job_id:
        raise ValueError(f"Worker `{worker_id}` is not assigned to job `{job_id}`")
    if job["status"] != "running":
        raise ValueError(f"Job `{job_id}` is not running")
    if job.get("worker_id") != worker_id:
        raise ValueError(f"Job `{job_id}` is not claimed by worker `{worker_id}`")
    if job_lease_expired(job):
        raise ValueError(f"Job `{job_id}` lease expired before execution")

    try:
        result = dispatch_job(job)
        completed = complete_job(job_id, result=result)
    except Exception as exc:
        completed = fail_job(job_id, exc=exc)
    finally:
        release_worker(worker_id)

    return completed


def run_next_job(worker_id: str) -> dict[str, Any] | None:
    job = claim_next_job(worker_id)
    if job is None:
        return None
    return run_claimed_job(worker_id, job["job_id"])
