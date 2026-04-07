from fastapi import FastAPI
from fastapi.responses import JSONResponse

from runtime.artifact import load_artifact
from runtime.approval import abort_approval, approve_approval, deny_approval, get_approval
from runtime.control_plane import workflow_control_view
from runtime.errors import ApprovalStateError, BudgetExceededError, DelegationDeniedError, PolicyDeniedError
from runtime.memory import delete_memory, list_memories, load_memory
from runtime.queue import create_job, list_jobs, load_job, promote_due_jobs, queue_summary, reschedule_job
from runtime.worker import (
    cancel_job_execution,
    claim_next_job,
    heartbeat_worker,
    list_workers,
    load_worker,
    reclaim_expired_leases,
    register_worker,
    run_claimed_job,
    run_next_job,
)
from runtime.workflow_runner import resume_workflow, start_child_workflow, start_workflow

app = FastAPI(title="ClarityOS", version="0.8.0")


@app.get("/status")
def status() -> dict[str, str]:
    return {"status": "ok"}


def error_status_code(exc: Exception) -> int:
    if isinstance(exc, FileNotFoundError):
        return 404
    if isinstance(exc, (DelegationDeniedError, PolicyDeniedError)):
        return 403
    if isinstance(exc, ApprovalStateError):
        return 409
    if isinstance(exc, BudgetExceededError):
        return 429
    if isinstance(exc, ValueError):
        return 400
    return 500


def error_response(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=error_status_code(exc),
        content={
            "status": "error",
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        },
    )


@app.post("/run")
def run(payload: dict):
    try:
        return workflow_run(payload)
    except Exception as exc:
        return error_response(exc)


def workflow_run(payload: dict):
    user_input = payload.get("input", "")
    agent_name = payload.get("agent", "default")
    tool_name = payload.get("tool")
    tool_args = payload.get("tool_args")
    approval_id = payload.get("approval_id")

    return start_workflow(
        user_input=user_input,
        agent_name=agent_name,
        tool_name=tool_name,
        tool_args=tool_args,
        approval_id=approval_id,
    )


def queue_job_request(payload: dict):
    job_type = payload.get("type", "workflow_start")
    workflow_id = payload.get("workflow_id")
    if job_type in {"workflow_resume", "workflow_subrun"} and not workflow_id:
        raise ValueError(f"Job type `{job_type}` requires `workflow_id`")

    job_payload = {
        "input": payload.get("input", ""),
        "agent": payload.get("agent", "default"),
        "tool": payload.get("tool"),
        "tool_args": payload.get("tool_args"),
        "approval_id": payload.get("approval_id"),
    }
    if workflow_id is not None:
        job_payload["workflow_id"] = workflow_id
    if job_type == "workflow_subrun":
        job_payload["role"] = payload.get("role")
        job_payload["allowed_capabilities"] = payload.get("allowed_capabilities")
        job_payload["allowed_tools"] = payload.get("allowed_tools")
        job_payload["shared_memory_ids"] = payload.get("shared_memory_ids")

    return create_job(
        job_type=job_type,
        payload=job_payload,
        priority=payload.get("priority", 100),
        delay_seconds=payload.get("delay_seconds", 0),
        run_at=payload.get("run_at"),
        workflow_id=workflow_id,
        parent_job_id=payload.get("parent_job_id"),
        idempotency_key=payload.get("idempotency_key"),
        max_attempts=payload.get("max_attempts", 1),
        retry_backoff_seconds=payload.get("retry_backoff_seconds", 30),
    )


@app.post("/workflows")
def workflow_start(payload: dict):
    try:
        return workflow_run(payload)
    except Exception as exc:
        return error_response(exc)


@app.post("/jobs")
def job_create(payload: dict):
    try:
        return queue_job_request(payload)
    except Exception as exc:
        return error_response(exc)


@app.post("/workers")
def worker_create(payload: dict):
    try:
        return register_worker(
            name=payload.get("name"),
            lease_seconds=payload.get("lease_seconds", 30),
        )
    except Exception as exc:
        return error_response(exc)


@app.get("/workers")
def worker_list():
    try:
        return {
            "workers": list_workers(),
        }
    except Exception as exc:
        return error_response(exc)


@app.get("/workers/{worker_id}")
def worker_status(worker_id: str):
    try:
        return load_worker(worker_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/workers/{worker_id}/heartbeat")
def worker_heartbeat(worker_id: str):
    try:
        return heartbeat_worker(worker_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/workers/{worker_id}/jobs/claim")
def worker_claim_job(worker_id: str):
    try:
        job = claim_next_job(worker_id)
        return {"job": job}
    except Exception as exc:
        return error_response(exc)


@app.post("/workers/{worker_id}/jobs/{job_id}/run")
def worker_run_claimed_job(worker_id: str, job_id: str):
    try:
        return run_claimed_job(worker_id, job_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/workers/{worker_id}/jobs/run-next")
def worker_run_next(worker_id: str):
    try:
        return {"job": run_next_job(worker_id)}
    except Exception as exc:
        return error_response(exc)


@app.post("/workers/reclaim-expired")
def worker_reclaim_expired():
    try:
        return reclaim_expired_leases()
    except Exception as exc:
        return error_response(exc)


@app.get("/jobs")
def job_list(status: str | None = None):
    try:
        return {
            "jobs": list_jobs(status=status),
        }
    except Exception as exc:
        return error_response(exc)


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    try:
        return load_job(job_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: str, payload: dict | None = None):
    try:
        reason = "operator"
        if payload is not None:
            reason = payload.get("reason", "operator")
        return cancel_job_execution(job_id, reason=reason)
    except Exception as exc:
        return error_response(exc)


@app.post("/jobs/{job_id}/reschedule")
def job_reschedule(job_id: str, payload: dict | None = None):
    try:
        body = payload or {}
        return reschedule_job(
            job_id,
            delay_seconds=body.get("delay_seconds", 0),
            run_at=body.get("run_at"),
        )
    except Exception as exc:
        return error_response(exc)


@app.get("/queue")
def queue_status():
    try:
        return queue_summary()
    except Exception as exc:
        return error_response(exc)


@app.post("/queue/promote-ready")
def queue_promote_ready(payload: dict | None = None):
    try:
        body = payload or {}
        return promote_due_jobs(limit=body.get("limit"))
    except Exception as exc:
        return error_response(exc)


@app.get("/approvals/{approval_id}")
def approval_status(approval_id: str):
    try:
        return get_approval(approval_id)
    except Exception as exc:
        return error_response(exc)


@app.get("/artifacts/{artifact_id}")
def artifact_status(artifact_id: str):
    try:
        return load_artifact(artifact_id)
    except Exception as exc:
        return error_response(exc)


def parse_tags_param(tags: str | None) -> list[str] | None:
    if tags is None:
        return None
    parsed = [tag.strip() for tag in tags.split(",") if tag.strip()]
    return parsed or None


@app.get("/memories")
def memory_list(
    memory_type: str | None = None,
    scope_kind: str | None = None,
    agent: str | None = None,
    workflow_id: str | None = None,
    run_id: str | None = None,
    tags: str | None = None,
    limit: int | None = None,
):
    try:
        return {
            "memories": list_memories(
                memory_type=memory_type,
                scope_kind=scope_kind,
                agent=agent,
                workflow_id=workflow_id,
                run_id=run_id,
                tags=parse_tags_param(tags),
                limit=limit,
            ),
        }
    except Exception as exc:
        return error_response(exc)


@app.get("/memories/{memory_id}")
def memory_status(memory_id: str):
    try:
        return load_memory(memory_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/memories/{memory_id}/delete")
def memory_delete(memory_id: str):
    try:
        return delete_memory(memory_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/approvals/{approval_id}/approve")
def approval_approve(approval_id: str):
    try:
        return approve_approval(approval_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/approvals/{approval_id}/deny")
def approval_deny(approval_id: str):
    try:
        return deny_approval(approval_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/approvals/{approval_id}/abort")
def approval_abort(approval_id: str):
    try:
        return abort_approval(approval_id)
    except Exception as exc:
        return error_response(exc)


@app.get("/workflows/{workflow_id}")
def workflow_status(workflow_id: str):
    try:
        return workflow_control_view(workflow_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/workflows/{workflow_id}/resume")
def workflow_resume(workflow_id: str):
    try:
        return resume_workflow(workflow_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/workflows/{workflow_id}/subruns")
def workflow_spawn_subrun(workflow_id: str, payload: dict):
    try:
        return start_child_workflow(
            workflow_id,
            user_input=payload.get("input", ""),
            agent_name=payload.get("agent", "default"),
            tool_name=payload.get("tool"),
            tool_args=payload.get("tool_args"),
            role=payload.get("role"),
            allowed_capabilities=payload.get("allowed_capabilities"),
            allowed_tools=payload.get("allowed_tools"),
            shared_memory_ids=payload.get("shared_memory_ids"),
        )
    except Exception as exc:
        return error_response(exc)
