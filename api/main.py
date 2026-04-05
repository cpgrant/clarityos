from fastapi import FastAPI

from runtime.agent import run_agent

app = FastAPI(title="ClarityOS", version="0.2.2")


@app.get("/status")
def status() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/run")
def run(payload: dict) -> dict:
    user_input = payload.get("input", "")
    agent_name = payload.get("agent", "default")
    tool_name = payload.get("tool")
    tool_args = payload.get("tool_args")

    return run_agent(
        user_input=user_input,
        agent_name=agent_name,
        tool_name=tool_name,
        tool_args=tool_args,
    )
