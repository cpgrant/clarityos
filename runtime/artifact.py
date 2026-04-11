import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.storage import ARTIFACT_DIR
from runtime.state import load_state_payload, write_state_payload

ARTIFACT_STATE_SCHEMA = "artifact.v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def artifact_path(artifact_id: str) -> Path:
    return ARTIFACT_DIR / f"{artifact_id}.json"


def ensure_artifact_dir() -> None:
    ARTIFACT_DIR.mkdir(exist_ok=True)


def artifact_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": artifact["artifact_id"],
        "workflow_id": artifact["workflow_id"],
        "run_id": artifact["run_id"],
        "name": artifact["name"],
        "kind": artifact["kind"],
        "created_at": artifact["created_at"],
        "updated_at": artifact["updated_at"],
        "metadata": dict(artifact.get("metadata", {})),
    }


def write_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    ensure_artifact_dir()
    path = artifact_path(artifact["artifact_id"])
    return write_state_payload(path, artifact, schema=ARTIFACT_STATE_SCHEMA)


def create_artifact(
    *,
    workflow_id: str,
    run_id: str,
    name: str,
    kind: str,
    value: Any,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = utc_now()
    artifact = {
        "artifact_id": str(uuid.uuid4()),
        "workflow_id": workflow_id,
        "run_id": run_id,
        "name": name,
        "kind": kind,
        "value": value,
        "metadata": metadata or {},
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    return write_artifact(artifact)


def load_artifact(artifact_id: str) -> dict[str, Any]:
    path = artifact_path(artifact_id)
    if not path.is_file():
        raise FileNotFoundError(f"Artifact not found: {artifact_id}")

    return load_state_payload(path, schema=ARTIFACT_STATE_SCHEMA)


def list_artifacts_for_workflow(workflow_id: str) -> list[dict[str, Any]]:
    if not ARTIFACT_DIR.is_dir():
        return []

    artifacts = []
    for path in sorted(ARTIFACT_DIR.glob("*.json")):
        artifact = load_state_payload(path, schema=ARTIFACT_STATE_SCHEMA)
        if artifact.get("workflow_id") == workflow_id:
            artifacts.append(artifact)

    return artifacts
