from fastapi import FastAPI
from fastapi.responses import JSONResponse

from runtime.approval import abort_approval, approve_approval, deny_approval, get_approval
from runtime.agent import run_agent
from runtime.errors import ApprovalStateError, BudgetExceededError, PolicyDeniedError

app = FastAPI(title="ClarityOS", version="0.4.0")


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
    user_input = payload.get("input", "")
    agent_name = payload.get("agent", "default")
    tool_name = payload.get("tool")
    tool_args = payload.get("tool_args")
    approval_id = payload.get("approval_id")

    try:
        return run_agent(
            user_input=user_input,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_args=tool_args,
            approval_id=approval_id,
        )
    except Exception as exc:
        return error_response(exc)


@app.get("/approvals/{approval_id}")
def approval_status(approval_id: str):
    try:
        return get_approval(approval_id)
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
