from pathlib import Path

import yaml

from runtime.model import call_model
from runtime.prompt_builder import build_prompt

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
    agent_config = load_agent(agent_name)
    prompt = build_prompt(user_input=user_input, config=agent_config)
    model_alias = agent_config["model"]
    model_result = call_model(model_name=model_alias, prompt=prompt)

    return {
        "agent": agent_name,
        "prompt": prompt,
        "provider": model_result["provider"],
        "model": model_result["model"],
        "output": model_result["output"],
    }
