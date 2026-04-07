import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from runtime.queue import (
    cancel_job,
    job_lease_expired,
    list_jobs,
    load_job,
    ready_jobs,
    record_job_failure,
    requeue_job,
    update_job,
)
from runtime.workflow_runner import resume_workflow, start_child_workflow, start_workflow


BASE_DIR = Path(__file__).resolve().parent.parent
WORKER_DIR = BASE_DIR / "workers"
DEFAULT_LEASE_SECONDS = 30


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_timestamp(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


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
        "created_at": worker["created_at"],
        "updated_at": worker["updated_at"],
    }


def write_worker(worker: dict[str, Any]) -> dict[str, Any]:
    ensure_worker_dir()
    path = worker_path(worker["worker_id"])
    with path.open("w", encoding="utf-8") as file:
        json.dump(worker_summary(worker), file, indent=2)
    return worker_summary(worker)


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
        "created_at": timestamp.isoformat(),
        "updated_at": timestamp.isoformat(),
    }
    return write_worker(worker)


def load_worker(worker_id: str) -> dict[str, Any]:
    path = worker_path(worker_id)
    if not path.is_file():
        raise FileNotFoundError(f"Worker not found: {worker_id}")

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def update_worker(worker_id: str, **changes: Any) -> dict[str, Any]:
    worker = load_worker(worker_id)
    updated = {
        **worker,
        **changes,
        "updated_at": utc_now_iso(),
    }
    return write_worker(updated)


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
    )


def list_workers() -> list[dict[str, Any]]:
    if not WORKER_DIR.is_dir():
        return []

    workers = []
    for path in sorted(WORKER_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as file:
            workers.append(json.load(file))
    return workers


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
    )
    update_worker(
        worker_id,
        status="busy",
        current_job_id=job["job_id"],
        last_heartbeat_at=timestamp.isoformat(),
        lease_expires_at=(timestamp + timedelta(seconds=worker["lease_seconds"])).isoformat(),
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
        )
    if job["job_type"] == "workflow_resume":
        return resume_workflow(payload["workflow_id"])
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
            shared_memory_ids=payload.get("shared_memory_ids"),
        )
    raise ValueError(f"Unsupported job type: {job['job_type']}")


def complete_job(job_id: str, *, result: dict[str, Any]) -> dict[str, Any]:
    return update_job(
        job_id,
        status="completed",
        result=result,
        error=None,
        lease_expires_at=None,
    )


def fail_job(job_id: str, *, exc: Exception) -> dict[str, Any]:
    return record_job_failure(job_id, exc=exc)


def release_worker(worker_id: str) -> dict[str, Any]:
    return update_worker(
        worker_id,
        status="idle",
        current_job_id=None,
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
