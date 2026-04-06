from fastapi import FastAPI
from fastapi.responses import JSONResponse

from runtime.artifact import load_artifact
from runtime.approval import abort_approval, approve_approval, deny_approval, get_approval
from runtime.control_plane import workflow_control_view
from runtime.errors import ApprovalStateError, BudgetExceededError, PolicyDeniedError
from runtime.workflow_runner import resume_workflow, start_child_workflow, start_workflow

app = FastAPI(title="ClarityOS", version="0.5.0")


@app.get("/status")
def status() -> dict[str, str]:
    return {"status": "ok"}


def error_status_code(exc: Exception) -> int:
    if isinstance(exc, FileNotFoundError):
        return 404
    if isinstance(exc, PolicyDeniedError):
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


@app.post("/workflows")
def workflow_start(payload: dict):
    try:
        return workflow_run(payload)
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
        )
    except Exception as exc:
        return error_response(exc)
