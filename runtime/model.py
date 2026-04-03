import json
import os
from pathlib import Path
from urllib import error, request

import yaml
from openai import OpenAI


DEBUG = os.getenv("CLARITY_DEBUG", "false").lower() == "true"

BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_CONFIG_PATH = BASE_DIR / "config" / "models.yaml"

openai_client = OpenAI()


def load_model_config(name: str) -> dict:
    with MODELS_CONFIG_PATH.open() as file:
        data = yaml.safe_load(file) or {}

    models = data.get("models", {})
    if name not in models:
        raise ValueError(f"Unknown model: {name}")

    return models[name]


def call_model(model_name: str, prompt: str) -> dict:
    model_config = load_model_config(model_name)
    provider = model_config["provider"]
    provider_id = model_config["provider_id"]

    if provider == "openai":
        return call_openai_model(provider_id=provider_id, prompt=prompt)
    if provider == "ollama":
        return call_ollama_model(provider_id=provider_id, prompt=prompt)

    raise ValueError(f"Unsupported provider: {provider}")


def call_openai_model(provider_id: str, prompt: str) -> dict:
    response = openai_client.responses.create(
        model=provider_id,
        input=prompt,
    )

    result = {
        "provider": "openai",
        "model": provider_id,
        "output": response.output_text,
    }

    if DEBUG:
        result["raw"] = response.model_dump()

    return result


def call_ollama_model(provider_id: str, prompt: str) -> dict:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    endpoint = f"{base_url}/api/generate"
    payload = json.dumps(
        {
            "model": provider_id,
            "prompt": prompt,
            "stream": False,
        }
    ).encode("utf-8")
    http_request = request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Ollama HTTP error ({exc.code}) at {endpoint}: {message}"
            ) from exc
    except error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {base_url}. Is `ollama serve` running?"
        ) from exc

    output = body.get("response", "")
    if not output:
        raise RuntimeError(f"Ollama returned empty response: {body}")

    result = {
        "provider": "ollama",
        "model": provider_id,
        "output": output,
    }

    if DEBUG:
        result["raw"] = body

    return result