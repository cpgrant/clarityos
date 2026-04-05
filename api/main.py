from fastapi import FastAPI
from fastapi.responses import JSONResponse

from runtime.agent import run_agent

app = FastAPI(title="ClarityOS", version="0.2.2")


@app.get("/status")
def status() -> dict[str, str]:
    return {"status": "ok"}


def error_status_code(exc: Exception) -> int:
    if isinstance(exc, FileNotFoundError):
        return 404
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

    try:
        return run_agent(
            user_input=user_input,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_args=tool_args,
        )
    except Exception as exc:
        return error_response(exc)
