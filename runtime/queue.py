import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
JOB_DIR = BASE_DIR / "jobs"

JOB_TYPES = {"workflow_start", "workflow_resume", "workflow_subrun"}
JOB_STATUSES = {"queued", "scheduled", "running", "completed", "failed", "dead_letter", "canceled"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_timestamp(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


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
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
        }

    data["lease_expired"] = job_lease_expired(data)
    return data


def write_job(job: QueueJob) -> dict[str, Any]:
    ensure_job_dir()
    path = job_path(job.job_id)
    snapshot = job_summary(job)
    with path.open("w", encoding="utf-8") as file:
        json.dump(snapshot, file, indent=2)
    return snapshot


def update_job(job_id: str, **changes: Any) -> dict[str, Any]:
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
    with path.open("w", encoding="utf-8") as file:
        json.dump(updated, file, indent=2)
    return job_summary(updated)


def _load_job_snapshot(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    normalize_job_type(data["job_type"])
    normalize_job_status(data["status"])
    normalize_priority(data["priority"])
    normalize_positive_int(data.get("max_attempts", 1), field_name="max_attempts")
    normalize_non_negative_int(
        data.get("retry_backoff_seconds", 30),
        field_name="retry_backoff_seconds",
    )
    normalize_non_negative_int(data.get("attempt_count", 0), field_name="attempt_count")
    return data


def find_job_by_idempotency_key(idempotency_key: str) -> dict[str, Any] | None:
    if not idempotency_key:
        raise ValueError("Job `idempotency_key` must be a non-empty string")
    if not JOB_DIR.is_dir():
        return None

    matches = []
    for path in JOB_DIR.glob("*.json"):
        with path.open(encoding="utf-8") as file:
            job = job_summary(json.load(file))
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
    )


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
        promoted = update_job(job["job_id"], status="queued")
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
    )
