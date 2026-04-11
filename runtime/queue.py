import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from runtime.storage import JOB_DIR
from runtime.state import load_state_payload, write_state_payload

JOB_STATE_SCHEMA = "job.v1"

JOB_TYPES = {"workflow_start", "workflow_resume", "workflow_subrun"}
JOB_STATUSES = {"queued", "scheduled", "running", "completed", "failed", "dead_letter", "canceled"}
TERMINAL_JOB_STATUSES = {"completed", "failed", "dead_letter", "canceled"}


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


def normalize_job_type(job_type: str) -> str:
    if job_type not in JOB_TYPES:
        raise ValueError(f"Unknown job type: {job_type}")
    return job_type


def normalize_job_status(status: str) -> str:
    if status not in JOB_STATUSES:
        raise ValueError(f"Unknown job status: {status}")
    return status


def normalize_priority(priority: Any) -> int:
    if not isinstance(priority, int):
        raise ValueError("Job priority must be an integer")
    return priority


def normalize_positive_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"Job `{field_name}` must be a positive integer")
    return value


def normalize_non_negative_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"Job `{field_name}` must be a non-negative integer")
    return value


def normalize_optional_limit(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"Queue `{field_name}` must be a positive integer")
    return value


def normalize_job_status_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return ["dead_letter"]
    if not isinstance(value, list) or not value:
        raise ValueError(f"Queue `{field_name}` must be a non-empty list")

    normalized = []
    seen = set()
    for raw_status in value:
        if not isinstance(raw_status, str) or not raw_status.strip():
            raise ValueError(f"Queue `{field_name}` must contain non-empty status strings")
        status = raw_status.strip()
        normalize_job_status(status)
        if status not in TERMINAL_JOB_STATUSES:
            raise ValueError(
                f"Queue `{field_name}` may only include terminal statuses: completed, failed, dead_letter, canceled"
            )
        if status not in seen:
            normalized.append(status)
            seen.add(status)
    return normalized


def normalize_transition_history(value: Any, *, field_name: str = "transition_history") -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Job `{field_name}` must be a list")

    normalized = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError(f"Job `{field_name}` entries must be objects")
        normalized.append(dict(entry))
    return normalized


def job_transition_changed_fields(current: dict[str, Any], updated: dict[str, Any]) -> dict[str, dict[str, Any]]:
    changed_fields = {}
    for field in [
        "status",
        "worker_id",
        "claimed_at",
        "lease_expires_at",
        "ready_at",
        "attempt_count",
        "next_retry_at",
        "reclaim_count",
        "dead_lettered_at",
        "canceled_at",
        "result",
        "error",
    ]:
        if current.get(field) != updated.get(field):
            changed_fields[field] = {
                "from": current.get(field),
                "to": updated.get(field),
            }
    return changed_fields


def classify_job_transition_event(current: dict[str, Any], updated: dict[str, Any]) -> str:
    if current.get("status") != updated.get("status"):
        from_status = current.get("status")
        to_status = updated.get("status")
        if to_status == "running":
            return "claimed"
        if to_status == "completed":
            return "completed"
        if to_status == "failed":
            return "failed"
        if to_status == "dead_letter":
            return "dead_lettered"
        if to_status == "canceled":
            return "canceled"
        if to_status == "scheduled" and updated.get("attempt_count", 0) > current.get("attempt_count", 0):
            return "retry_scheduled"
        if to_status == "queued" and from_status == "running":
            return "requeued"
        if to_status == "queued" and from_status in {"failed", "dead_letter", "scheduled"}:
            return "rescheduled"
        return "status_changed"
    if current.get("worker_id") != updated.get("worker_id"):
        return "worker_assignment_changed"
    if current.get("reclaim_count", 0) != updated.get("reclaim_count", 0):
        return "reclaimed"
    if current.get("ready_at") != updated.get("ready_at"):
        return "ready_at_changed"
    return "updated"


def build_job_transition_history(
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
                "ready_at": updated["ready_at"],
                "priority": updated["priority"],
            }
        )
        return history

    changed_fields = job_transition_changed_fields(previous, updated)
    if not changed_fields:
        return history

    history.append(
        {
            "event_type": classify_job_transition_event(previous, updated),
            "timestamp": timestamp,
            "from_status": previous.get("status"),
            "to_status": updated.get("status"),
            "worker_id": updated.get("worker_id"),
            "attempt_count": updated.get("attempt_count", 0),
            "reason": transition_reason
            or updated.get("cancel_reason")
            or updated.get("last_requeue_reason")
            or (updated.get("error") or {}).get("message"),
            "changed_fields": changed_fields,
            "details": dict(transition_details or {}),
        }
    )
    return history


def ensure_job_dir() -> None:
    JOB_DIR.mkdir(exist_ok=True)


def job_path(job_id: str) -> Path:
    return JOB_DIR / f"{job_id}.json"


def job_status_for_ready_at(ready_at: str) -> str:
    if parse_timestamp(ready_at) > utc_now():
        return "scheduled"
    return "queued"


def build_ready_at(*, delay_seconds: int = 0, run_at: str | None = None) -> str:
    if run_at is not None and delay_seconds:
        raise ValueError("Job accepts either `delay_seconds` or `run_at`, not both")
    if run_at is not None:
        return parse_timestamp(run_at).isoformat()
    if not isinstance(delay_seconds, int) or delay_seconds < 0:
        raise ValueError("Job `delay_seconds` must be a non-negative integer")
    return (utc_now() + timedelta(seconds=delay_seconds)).isoformat()


@dataclass
class QueueJob:
    job_id: str
    job_type: str
    status: str
    priority: int
    ready_at: str
    payload: dict[str, Any]
    workflow_id: str | None
    parent_job_id: str | None
    idempotency_key: str | None
    worker_id: str | None
    claimed_at: str | None
    lease_expires_at: str | None
    reclaim_count: int
    last_requeue_reason: str | None
    attempt_count: int
    max_attempts: int
    retry_backoff_seconds: int
    last_failure_at: str | None
    next_retry_at: str | None
    dead_lettered_at: str | None
    canceled_at: str | None
    cancel_reason: str | None
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    transition_history: list[dict[str, Any]]
    created_at: str
    updated_at: str


def job_summary(job: QueueJob | dict[str, Any]) -> dict[str, Any]:
    if isinstance(job, QueueJob):
        data = {
            "job_id": job.job_id,
            "job_type": job.job_type,
            "status": job.status,
            "priority": job.priority,
            "ready_at": job.ready_at,
            "payload": dict(job.payload),
            "workflow_id": job.workflow_id,
            "parent_job_id": job.parent_job_id,
            "idempotency_key": job.idempotency_key,
            "worker_id": job.worker_id,
            "claimed_at": job.claimed_at,
            "lease_expires_at": job.lease_expires_at,
            "reclaim_count": job.reclaim_count,
            "last_requeue_reason": job.last_requeue_reason,
            "attempt_count": job.attempt_count,
            "max_attempts": job.max_attempts,
            "retry_backoff_seconds": job.retry_backoff_seconds,
            "last_failure_at": job.last_failure_at,
            "next_retry_at": job.next_retry_at,
            "dead_lettered_at": job.dead_lettered_at,
            "canceled_at": job.canceled_at,
            "cancel_reason": job.cancel_reason,
            "result": dict(job.result) if job.result is not None else None,
            "error": dict(job.error) if job.error is not None else None,
            "transition_history": [dict(entry) for entry in job.transition_history],
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }
    else:
        data = {
            "job_id": job["job_id"],
            "job_type": job["job_type"],
            "status": job["status"],
            "priority": job["priority"],
            "ready_at": job["ready_at"],
            "payload": dict(job.get("payload", {})),
            "workflow_id": job.get("workflow_id"),
            "parent_job_id": job.get("parent_job_id"),
            "idempotency_key": job.get("idempotency_key"),
            "worker_id": job.get("worker_id"),
            "claimed_at": job.get("claimed_at"),
            "lease_expires_at": job.get("lease_expires_at"),
            "reclaim_count": job.get("reclaim_count", 0),
            "last_requeue_reason": job.get("last_requeue_reason"),
            "attempt_count": job.get("attempt_count", 0),
            "max_attempts": job.get("max_attempts", 1),
            "retry_backoff_seconds": job.get("retry_backoff_seconds", 30),
            "last_failure_at": job.get("last_failure_at"),
            "next_retry_at": job.get("next_retry_at"),
            "dead_lettered_at": job.get("dead_lettered_at"),
            "canceled_at": job.get("canceled_at"),
            "cancel_reason": job.get("cancel_reason"),
            "result": dict(job.get("result", {})) if job.get("result") is not None else None,
            "error": dict(job.get("error", {})) if job.get("error") is not None else None,
            "transition_history": normalize_transition_history(job.get("transition_history")),
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
        }

    data["lease_expired"] = job_lease_expired(data)
    return data


def write_job(job: QueueJob) -> dict[str, Any]:
    ensure_job_dir()
    path = job_path(job.job_id)
    snapshot = job_summary(job)
    previous = load_state_payload(path, schema=JOB_STATE_SCHEMA) if path.is_file() else None
    snapshot["transition_history"] = build_job_transition_history(previous, snapshot)
    return write_state_payload(path, snapshot, schema=JOB_STATE_SCHEMA)


def update_job(
    job_id: str,
    *,
    transition_reason: str | None = None,
    transition_details: dict[str, Any] | None = None,
    **changes: Any,
) -> dict[str, Any]:
    path = job_path(job_id)
    if not path.is_file():
        raise FileNotFoundError(f"Job not found: {job_id}")
    current = _load_job_snapshot(path)
    updated = {
        **current,
        **changes,
        "updated_at": utc_now_iso(),
    }
    normalize_job_type(updated["job_type"])
    normalize_job_status(updated["status"])
    normalize_priority(updated["priority"])
    normalize_positive_int(updated.get("max_attempts", 1), field_name="max_attempts")
    normalize_non_negative_int(
        updated.get("retry_backoff_seconds", 30),
        field_name="retry_backoff_seconds",
    )
    normalize_non_negative_int(updated.get("attempt_count", 0), field_name="attempt_count")
    updated["transition_history"] = build_job_transition_history(
        current,
        updated,
        transition_reason=transition_reason,
        transition_details=transition_details,
    )
    return write_state_payload(path, updated, schema=JOB_STATE_SCHEMA)


def _load_job_snapshot(path: Path) -> dict[str, Any]:
    data = load_state_payload(path, schema=JOB_STATE_SCHEMA)
    normalize_job_type(data["job_type"])
    normalize_job_status(data["status"])
    normalize_priority(data["priority"])
    normalize_positive_int(data.get("max_attempts", 1), field_name="max_attempts")
    normalize_non_negative_int(
        data.get("retry_backoff_seconds", 30),
        field_name="retry_backoff_seconds",
    )
    normalize_non_negative_int(data.get("attempt_count", 0), field_name="attempt_count")
    data["transition_history"] = normalize_transition_history(data.get("transition_history"))
    return data


def find_job_by_idempotency_key(idempotency_key: str) -> dict[str, Any] | None:
    if not idempotency_key:
        raise ValueError("Job `idempotency_key` must be a non-empty string")
    if not JOB_DIR.is_dir():
        return None

    matches = []
    for path in JOB_DIR.glob("*.json"):
        job = job_summary(_load_job_snapshot(path))
        if job.get("idempotency_key") == idempotency_key:
            matches.append(job)

    if not matches:
        return None

    matches.sort(key=lambda job: (job["created_at"], job["job_id"]), reverse=True)
    return matches[0]


def idempotent_request_matches(
    existing_job: dict[str, Any],
    *,
    job_type: str,
    payload: dict[str, Any],
    workflow_id: str | None,
    parent_job_id: str | None,
) -> bool:
    return (
        existing_job["job_type"] == job_type
        and existing_job["payload"] == payload
        and existing_job.get("workflow_id") == workflow_id
        and existing_job.get("parent_job_id") == parent_job_id
    )


def create_job(
    *,
    job_type: str,
    payload: dict[str, Any],
    priority: int = 100,
    delay_seconds: int = 0,
    run_at: str | None = None,
    workflow_id: str | None = None,
    parent_job_id: str | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 1,
    retry_backoff_seconds: int = 30,
) -> dict[str, Any]:
    normalize_job_type(job_type)
    if not isinstance(payload, dict):
        raise ValueError("Job payload must be an object")
    if idempotency_key is not None and not isinstance(idempotency_key, str):
        raise ValueError("Job `idempotency_key` must be a string")
    if isinstance(idempotency_key, str) and not idempotency_key.strip():
        raise ValueError("Job `idempotency_key` must not be empty")
    max_attempts = normalize_positive_int(max_attempts, field_name="max_attempts")
    retry_backoff_seconds = normalize_non_negative_int(
        retry_backoff_seconds,
        field_name="retry_backoff_seconds",
    )

    normalized_payload = dict(payload)
    if idempotency_key:
        existing_job = find_job_by_idempotency_key(idempotency_key)
        if existing_job is not None:
            if not idempotent_request_matches(
                existing_job,
                job_type=job_type,
                payload=normalized_payload,
                workflow_id=workflow_id,
                parent_job_id=parent_job_id,
            ):
                raise ValueError(
                    f"Idempotency key `{idempotency_key}` is already used by a different job request"
                )
            return existing_job

    ready_at = build_ready_at(delay_seconds=delay_seconds, run_at=run_at)
    timestamp = utc_now_iso()
    job = QueueJob(
        job_id=str(uuid.uuid4()),
        job_type=job_type,
        status=job_status_for_ready_at(ready_at),
        priority=normalize_priority(priority),
        ready_at=ready_at,
        payload=normalized_payload,
        workflow_id=workflow_id,
        parent_job_id=parent_job_id,
        idempotency_key=idempotency_key,
        worker_id=None,
        claimed_at=None,
        lease_expires_at=None,
        reclaim_count=0,
        last_requeue_reason=None,
        attempt_count=0,
        max_attempts=max_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        last_failure_at=None,
        next_retry_at=None,
        dead_lettered_at=None,
        canceled_at=None,
        cancel_reason=None,
        result=None,
        error=None,
        transition_history=[],
        created_at=timestamp,
        updated_at=timestamp,
    )
    return write_job(job)


def load_job(job_id: str) -> dict[str, Any]:
    path = job_path(job_id)
    if not path.is_file():
        raise FileNotFoundError(f"Job not found: {job_id}")

    data = _load_job_snapshot(path)
    if data["status"] == "scheduled" and job_status_for_ready_at(data["ready_at"]) == "queued":
        return update_job(job_id, status="queued")
    return job_summary(data)


def list_jobs(*, status: str | None = None, promote_due: bool = True) -> list[dict[str, Any]]:
    if status is not None:
        normalize_job_status(status)
    if promote_due:
        promote_due_jobs()
    if not JOB_DIR.is_dir():
        return []

    jobs = []
    for path in JOB_DIR.glob("*.json"):
        job = job_summary(_load_job_snapshot(path))
        if status is None or job["status"] == status:
            jobs.append(job)

    jobs.sort(
        key=lambda job: (
            0 if job["status"] == "queued" else 1,
            -job["priority"],
            job["ready_at"],
            job["created_at"],
        )
    )
    return jobs


def ready_jobs() -> list[dict[str, Any]]:
    return [job for job in list_jobs() if job["status"] == "queued"]


def job_lease_expired(job: dict[str, Any]) -> bool:
    if job.get("status") != "running":
        return False
    lease_expires_at = job.get("lease_expires_at")
    if not lease_expires_at:
        return False
    return parse_timestamp(lease_expires_at) <= utc_now()


def requeue_job(job_id: str, *, reason: str) -> dict[str, Any]:
    job = load_job(job_id)
    return update_job(
        job_id,
        status="queued",
        worker_id=None,
        claimed_at=None,
        lease_expires_at=None,
        reclaim_count=job.get("reclaim_count", 0) + 1,
        last_requeue_reason=reason,
        next_retry_at=None,
        transition_reason=reason,
    )


def retry_delay_seconds(job: dict[str, Any], *, attempt_count: int) -> int:
    base = job.get("retry_backoff_seconds", 30)
    if base == 0:
        return 0
    return base * (2 ** max(attempt_count - 1, 0))


def record_job_failure(job_id: str, *, exc: Exception) -> dict[str, Any]:
    job = load_job(job_id)
    attempted = job.get("attempt_count", 0) + 1
    timestamp = utc_now_iso()
    error = {
        "type": type(exc).__name__,
        "message": str(exc),
    }

    if attempted >= job.get("max_attempts", 1):
        terminal_status = "dead_letter" if job.get("max_attempts", 1) > 1 else "failed"
        return update_job(
            job_id,
            status=terminal_status,
            attempt_count=attempted,
            error=error,
            last_failure_at=timestamp,
            dead_lettered_at=timestamp if terminal_status == "dead_letter" else None,
            next_retry_at=None,
            worker_id=None,
            claimed_at=None,
            lease_expires_at=None,
            transition_reason=str(exc),
            transition_details={"terminal": True},
        )

    delay = retry_delay_seconds(job, attempt_count=attempted)
    next_retry_at = build_ready_at(delay_seconds=delay)
    return update_job(
        job_id,
        status=job_status_for_ready_at(next_retry_at),
        attempt_count=attempted,
        error=error,
        last_failure_at=timestamp,
        next_retry_at=next_retry_at,
        ready_at=next_retry_at,
        worker_id=None,
        claimed_at=None,
        lease_expires_at=None,
        last_requeue_reason=f"Retry {attempted} scheduled after failure",
        result=None,
        transition_reason=str(exc),
        transition_details={"retry_delay_seconds": delay},
    )


def repair_stale_job_state(*, limit: int | None = None) -> dict[str, Any]:
    limit = normalize_optional_limit(limit, field_name="repair_stale.limit")

    repaired = []
    for job in list_jobs(promote_due=False):
        changes = {}
        reasons = []

        if job["status"] == "scheduled" and job_status_for_ready_at(job["ready_at"]) == "queued":
            changes["status"] = "queued"
            reasons.append("Promoted due scheduled job to queued")

        if job["status"] != "running":
            if job.get("worker_id") is not None:
                changes["worker_id"] = None
                reasons.append("Cleared stale worker assignment")
            if job.get("claimed_at") is not None:
                changes["claimed_at"] = None
                reasons.append("Cleared stale claim timestamp")
            if job.get("lease_expires_at") is not None:
                changes["lease_expires_at"] = None
                reasons.append("Cleared stale lease expiration")

        if not changes:
            continue

        repaired_job = update_job(
            job["job_id"],
            transition_reason="stale_state_repair",
            transition_details={"reasons": reasons},
            **changes,
        )
        repaired.append(
            {
                "job_id": repaired_job["job_id"],
                "status": repaired_job["status"],
                "reasons": reasons,
            }
        )
        if limit is not None and len(repaired) >= limit:
            break

    return {
        "repaired_jobs": repaired,
        "repaired_job_ids": [job["job_id"] for job in repaired],
        "repaired_count": len(repaired),
    }


def promote_due_jobs(*, limit: int | None = None) -> dict[str, Any]:
    if limit is not None:
        if not isinstance(limit, int) or limit <= 0:
            raise ValueError("Queue promotion `limit` must be a positive integer")
    if not JOB_DIR.is_dir():
        return {
            "promoted_job_ids": [],
            "promoted_count": 0,
        }

    scheduled = []
    for path in JOB_DIR.glob("*.json"):
        job = _load_job_snapshot(path)
        if job["status"] == "scheduled" and job_status_for_ready_at(job["ready_at"]) == "queued":
            scheduled.append(job)

    scheduled.sort(key=lambda job: (job["ready_at"], -job["priority"], job["created_at"]))
    if limit is not None:
        scheduled = scheduled[:limit]

    promoted_job_ids = []
    for job in scheduled:
        promoted = update_job(
            job["job_id"],
            status="queued",
            transition_reason="ready_at_elapsed",
        )
        promoted_job_ids.append(promoted["job_id"])

    return {
        "promoted_job_ids": promoted_job_ids,
        "promoted_count": len(promoted_job_ids),
    }


def queue_summary() -> dict[str, Any]:
    promotion = promote_due_jobs()
    jobs = list_jobs(promote_due=False)
    counts = {status: 0 for status in sorted(JOB_STATUSES)}
    for job in jobs:
        counts[job["status"]] += 1

    queued_jobs = [job for job in jobs if job["status"] == "queued"]
    scheduled_jobs = [job for job in jobs if job["status"] == "scheduled"]
    running_jobs = [job for job in jobs if job["status"] == "running"]
    dead_letter_jobs = [job for job in jobs if job["status"] == "dead_letter"]
    retry_scheduled_jobs = [job for job in scheduled_jobs if job.get("attempt_count", 0) > 0]
    oldest_queued_at = min((job["created_at"] for job in queued_jobs), default=None)
    next_ready_at = min((job["ready_at"] for job in scheduled_jobs), default=None)
    return {
        "counts": counts,
        "total_jobs": len(jobs),
        "queued_job_ids": [job["job_id"] for job in queued_jobs],
        "running_job_ids": [job["job_id"] for job in running_jobs],
        "dead_letter_job_ids": [job["job_id"] for job in dead_letter_jobs],
        "retry_scheduled_job_ids": [job["job_id"] for job in retry_scheduled_jobs],
        "oldest_queued_at": oldest_queued_at,
        "next_ready_at": next_ready_at,
        "retry_pending_count": len(retry_scheduled_jobs),
        "dead_letter_count": len(dead_letter_jobs),
        "promoted_count": promotion["promoted_count"],
        "promoted_job_ids": promotion["promoted_job_ids"],
    }


def queue_health_summary() -> dict[str, Any]:
    summary = queue_summary()
    jobs = list_jobs(promote_due=False)
    queued_jobs = [job for job in jobs if job["status"] == "queued"]
    scheduled_jobs = [job for job in jobs if job["status"] == "scheduled"]
    running_jobs = [job for job in jobs if job["status"] == "running"]
    retry_scheduled_jobs = [job for job in scheduled_jobs if job.get("attempt_count", 0) > 0]
    failed_jobs = [job for job in jobs if job["status"] == "failed"]
    dead_letter_jobs = [job for job in jobs if job["status"] == "dead_letter"]

    oldest_queued = min((job["created_at"] for job in queued_jobs), default=None)
    next_ready = min((job["ready_at"] for job in scheduled_jobs), default=None)
    oldest_retry = min((job.get("next_retry_at") or job["ready_at"] for job in retry_scheduled_jobs), default=None)
    claim_ages = [duration_seconds_since(job.get("claimed_at")) for job in running_jobs if job.get("claimed_at") is not None]
    claim_ages = [age for age in claim_ages if age is not None]
    expired_running_jobs = [job["job_id"] for job in running_jobs if job_lease_expired(job)]
    lifecycle_counts = {
        "claimed": 0,
        "retry_scheduled": 0,
        "requeued": 0,
        "rescheduled": 0,
        "completed": 0,
        "failed": 0,
        "dead_lettered": 0,
        "canceled": 0,
    }
    recent_lifecycle_events = []
    for job in jobs:
        for entry in job.get("transition_history", []):
            event_type = entry.get("event_type")
            changed_fields = entry.get("changed_fields") or {}
            attempt_change = changed_fields.get("attempt_count") or {}
            if event_type in lifecycle_counts:
                lifecycle_counts[event_type] += 1
                recent_lifecycle_events.append(
                    {
                        "event_type": event_type,
                        "job_id": job["job_id"],
                        "timestamp": entry.get("timestamp"),
                        "reason": entry.get("reason"),
                        "worker_id": changed_fields.get("worker_id", {}).get("to"),
                    }
                )
            if (
                entry.get("to_status") == "scheduled"
                and attempt_change.get("to") is not None
                and attempt_change.get("to", 0) > attempt_change.get("from", 0)
                and event_type != "retry_scheduled"
            ):
                lifecycle_counts["retry_scheduled"] += 1
                recent_lifecycle_events.append(
                    {
                        "event_type": "retry_scheduled",
                        "job_id": job["job_id"],
                        "timestamp": entry.get("timestamp"),
                        "reason": entry.get("reason"),
                        "worker_id": changed_fields.get("worker_id", {}).get("to"),
                    }
                )
    recent_events = []
    for job in jobs:
        if job["status"] == "dead_letter":
            recent_events.append(
                {
                    "event_type": "dead_letter",
                    "job_id": job["job_id"],
                    "timestamp": job.get("dead_lettered_at") or job["updated_at"],
                    "message": (job.get("error") or {}).get("message"),
                }
            )
        elif job["status"] == "failed":
            recent_events.append(
                {
                    "event_type": "failed",
                    "job_id": job["job_id"],
                    "timestamp": job.get("last_failure_at") or job["updated_at"],
                    "message": (job.get("error") or {}).get("message"),
                }
            )
        elif job["status"] == "scheduled" and job.get("attempt_count", 0) > 0:
            recent_events.append(
                {
                    "event_type": "retry_pending",
                    "job_id": job["job_id"],
                    "timestamp": job.get("next_retry_at") or job["updated_at"],
                    "message": job.get("last_requeue_reason"),
                }
            )
        elif job.get("reclaim_count", 0) > 0:
            recent_events.append(
                {
                    "event_type": "reclaimed",
                    "job_id": job["job_id"],
                    "timestamp": job["updated_at"],
                    "message": job.get("last_requeue_reason"),
                }
            )
    recent_events.sort(key=lambda event: (event["timestamp"] or "", event["job_id"]), reverse=True)
    recent_lifecycle_events.sort(key=lambda event: (event["timestamp"] or "", event["job_id"]), reverse=True)

    return {
        **summary,
        "health": {
            "oldest_queued_age_seconds": duration_seconds_since(oldest_queued),
            "next_ready_in_seconds": (
                max(int((parse_timestamp(next_ready) - utc_now()).total_seconds()), 0)
                if next_ready is not None
                else None
            ),
            "oldest_retry_age_seconds": duration_seconds_since(oldest_retry),
            "retry_backlog_count": len(retry_scheduled_jobs),
            "failed_count": len(failed_jobs),
            "dead_letter_count": len(dead_letter_jobs),
            "expired_running_job_ids": expired_running_jobs,
            "expired_running_count": len(expired_running_jobs),
            "max_running_claim_age_seconds": max(claim_ages, default=None),
            "oldest_running_claim_age_seconds": max(claim_ages, default=None),
            "lifecycle": {
                "counts": lifecycle_counts,
                "recent_events": recent_lifecycle_events[:10],
            },
            "trends": {
                "recent_failures_last_hour": sum(
                    1 for job in failed_jobs if occurred_within_seconds(job.get("last_failure_at") or job["updated_at"], seconds=3600)
                ),
                "recent_dead_letters_last_hour": sum(
                    1 for job in dead_letter_jobs if occurred_within_seconds(job.get("dead_lettered_at") or job["updated_at"], seconds=3600)
                ),
                "recent_retries_last_hour": sum(
                    1 for job in retry_scheduled_jobs if occurred_within_seconds(job.get("next_retry_at") or job["updated_at"], seconds=3600)
                ),
                "reclaimed_jobs_total": sum(job.get("reclaim_count", 0) for job in jobs),
                "recent_events": recent_events[:5],
            },
        },
    }


def job_terminal_timestamp(job: dict[str, Any]) -> str:
    if job["status"] == "dead_letter" and job.get("dead_lettered_at") is not None:
        return job["dead_lettered_at"]
    if job["status"] == "canceled" and job.get("canceled_at") is not None:
        return job["canceled_at"]
    return job["updated_at"]


def prune_jobs(
    *,
    statuses: list[str] | None = None,
    older_than_seconds: int = 0,
    limit: int | None = None,
) -> dict[str, Any]:
    statuses = normalize_job_status_list(statuses, field_name="prune.statuses")
    older_than_seconds = normalize_non_negative_int(
        older_than_seconds,
        field_name="prune.older_than_seconds",
    )
    limit = normalize_optional_limit(limit, field_name="prune.limit")

    if not JOB_DIR.is_dir():
        return {
            "statuses": statuses,
            "older_than_seconds": older_than_seconds,
            "pruned_job_ids": [],
            "pruned_count": 0,
        }

    cutoff = utc_now() - timedelta(seconds=older_than_seconds)
    candidates = []
    for job in list_jobs(promote_due=False):
        if job["status"] not in statuses:
            continue
        terminal_at = parse_timestamp(job_terminal_timestamp(job))
        if terminal_at > cutoff:
            continue
        candidates.append(job)

    candidates.sort(key=lambda job: (job_terminal_timestamp(job), job["job_id"]))
    if limit is not None:
        candidates = candidates[:limit]

    pruned_job_ids = []
    for job in candidates:
        path = job_path(job["job_id"])
        if path.is_file():
            path.unlink()
            pruned_job_ids.append(job["job_id"])

    return {
        "statuses": statuses,
        "older_than_seconds": older_than_seconds,
        "pruned_job_ids": pruned_job_ids,
        "pruned_count": len(pruned_job_ids),
    }


def cancel_job(job_id: str, *, reason: str = "operator") -> dict[str, Any]:
    job = load_job(job_id)
    if job["status"] in {"completed", "failed", "dead_letter", "canceled"}:
        raise ValueError(f"Job `{job_id}` cannot be canceled from status `{job['status']}`")
    timestamp = utc_now_iso()
    return update_job(
        job_id,
        status="canceled",
        canceled_at=timestamp,
        cancel_reason=reason,
        worker_id=None if job["status"] != "running" else job.get("worker_id"),
        claimed_at=None,
        lease_expires_at=None,
        next_retry_at=None,
        result=None,
        error=None,
        transition_reason=reason,
    )


def reschedule_job(
    job_id: str,
    *,
    delay_seconds: int = 0,
    run_at: str | None = None,
) -> dict[str, Any]:
    job = load_job(job_id)
    if job["status"] not in {"queued", "scheduled", "failed", "dead_letter"}:
        raise ValueError(f"Job `{job_id}` cannot be rescheduled from status `{job['status']}`")

    ready_at = build_ready_at(delay_seconds=delay_seconds, run_at=run_at)
    return update_job(
        job_id,
        status=job_status_for_ready_at(ready_at),
        ready_at=ready_at,
        worker_id=None,
        claimed_at=None,
        lease_expires_at=None,
        last_requeue_reason=None,
        attempt_count=0,
        last_failure_at=None,
        dead_lettered_at=None,
        next_retry_at=None,
        canceled_at=None,
        cancel_reason=None,
        result=None,
        error=None,
        transition_reason="operator_reschedule",
        transition_details={"ready_at": ready_at},
    )
