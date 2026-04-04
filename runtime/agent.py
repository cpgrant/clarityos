import time
import uuid
from pathlib import Path

import yaml

from runtime.model import call_model
from runtime.prompt_builder import build_prompt
from runtime.trace import trace_run

BASE_DIR = Path(__file__).resolve().parent.parent
AGENTS_CONFIG_PATH = BASE_DIR / "config" / "agents.yaml"


def load_agent(agent_name: str) -> dict:
    with AGENTS_CONFIG_PATH.open() as file:
        data = yaml.safe_load(file) or {}

    agents = data.get("agents", {})
    if agent_name not in agents:
        raise ValueError(f"Unknown agent: {agent_name}")

    return agents[agent_name]


def run_agent(user_input: str, agent_name: str) -> dict:
    run_id = str(uuid.uuid4())
    start_time = time.perf_counter()
    prompt = None
    model_alias = None

    try:
        agent_config = load_agent(agent_name)
        prompt = build_prompt(user_input=user_input, config=agent_config)
        model_alias = agent_config["model"]
        model_result = call_model(model_name=model_alias, prompt=prompt)
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        trace_run(
            {
                "run_id": run_id,
                "status": "error",
                "duration_ms": duration_ms,
                "input": user_input,
                "agent": agent_name,
                "prompt": prompt,
                "model_alias": model_alias,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
        )
        raise

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    trace_run(
        {
            "run_id": run_id,
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
        "agent": agent_name,
        "prompt": prompt,
        "provider": model_result["provider"],
        "model": model_result["model"],
        "output": model_result["output"],
    }
