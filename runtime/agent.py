import time
import uuid
from pathlib import Path

import yaml

from runtime.model import call_model
from runtime.prompt_builder import build_prompt
from runtime.trace import trace_run
from runtime.tools import call_tool

BASE_DIR = Path(__file__).resolve().parent.parent
AGENTS_CONFIG_PATH = BASE_DIR / "config" / "agents.yaml"


def load_agent(agent_name: str) -> dict:
    with AGENTS_CONFIG_PATH.open() as file:
        data = yaml.safe_load(file) or {}

    agents = data.get("agents", {})
    if agent_name not in agents:
        raise ValueError(f"Unknown agent: {agent_name}")

    return agents[agent_name]


def run_agent(
    user_input: str,
    agent_name: str,
    tool_name: str | None = None,
    tool_args: dict | None = None,
) -> dict:
    run_id = str(uuid.uuid4())
    start_time = time.perf_counter()
    prompt = None
    model_alias = None
    tool_output = None
    run_type = "tool" if tool_name is not None else "model"

    try:
        agent_config = load_agent(agent_name)
        allowed_tools = agent_config.get("tools", []) or []

        if tool_name is not None:
            if tool_args is not None and not isinstance(tool_args, dict):
                raise ValueError("Tool arguments must be an object")

            if tool_name not in allowed_tools:
                raise ValueError(f"Tool not allowed for agent `{agent_name}`: {tool_name}")

            tool_result = call_tool(name=tool_name, args=tool_args)
            tool_output = tool_result["output"]

            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            trace_run(
                {
                    "run_id": run_id,
                    "run_type": run_type,
                    "status": "success",
                    "duration_ms": duration_ms,
                    "input": user_input,
                    "agent": agent_name,
                    "prompt": prompt,
                    "model_alias": model_alias,
                    "tool_name": tool_result["name"],
                    "tool_args": tool_result["args"],
                    "tool_output": tool_output,
                    "tool_ok": tool_result["ok"],
                    "output": tool_output,
                }
            )

            return {
                "status": "success",
                "run_type": run_type,
                "agent": agent_name,
                "prompt": prompt,
                "provider": None,
                "model": None,
                "tool": tool_result["name"],
                "tool_args": tool_result["args"],
                "tool_output": tool_output,
                "output": tool_output,
            }

        prompt = build_prompt(user_input=user_input, config=agent_config)
        model_alias = agent_config["model"]
        model_result = call_model(model_name=model_alias, prompt=prompt)
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        trace_payload = {
            "run_id": run_id,
            "run_type": run_type,
            "status": "error",
            "duration_ms": duration_ms,
            "input": user_input,
            "agent": agent_name,
            "prompt": prompt,
            "model_alias": model_alias,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
        if tool_name is not None:
            trace_payload.update(
                {
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "tool_output": tool_output,
                    "tool_ok": False,
                    "tool_error": str(exc),
                }
            )
        trace_run(trace_payload)
        raise

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    trace_run(
        {
            "run_id": run_id,
            "run_type": run_type,
            "status": "success",
            "duration_ms": duration_ms,
            "input": user_input,
            "agent": agent_name,
            "prompt": prompt,
            "model_alias": model_alias,
            "provider": model_result["provider"],
            "model": model_result["model"],
            "output": model_result["output"],
        }
    )

    return {
        "status": "success",
        "run_type": run_type,
        "agent": agent_name,
        "prompt": prompt,
        "provider": model_result["provider"],
        "model": model_result["model"],
        "tool": None,
        "tool_args": None,
        "tool_output": None,
        "output": model_result["output"],
    }
