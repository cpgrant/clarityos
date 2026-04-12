from pathlib import Path
import os
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
STATE_ROOT_ENV_VAR = "CLARITYCLAW_STATE_ROOT"
LEGACY_STATE_ROOT_ENV_VAR = "CLARITYOS_STATE_ROOT"


def _first_env_value(*names: str) -> str | None:
    for name in names:
        configured = os.getenv(name)
        if isinstance(configured, str) and configured.strip():
            return configured.strip()
    return None


def state_root() -> Path:
    configured = _first_env_value(STATE_ROOT_ENV_VAR, LEGACY_STATE_ROOT_ENV_VAR)
    if configured is not None:
        return Path(configured)
    return BASE_DIR


def state_directory(name: str) -> Path:
    return state_root() / name


SESSION_DIR = state_directory("sessions")
WORKFLOW_DIR = state_directory("workflows")
JOB_DIR = state_directory("jobs")
WORKER_DIR = state_directory("workers")
MEMORY_DIR = state_directory("memories")
ARTIFACT_DIR = state_directory("artifacts")
APPROVAL_DIR = state_directory("approvals")
LOG_DIR = state_directory("logs")


def storage_layout() -> dict[str, dict[str, Any]]:
    root = state_root()
    return {
        "sessions": {
            "path": str(root / "sessions"),
            "backup_priority": "critical",
            "preserve_on_restart": True,
            "mount_recommended": True,
            "regenerable": False,
            "description": "Session ownership, message history, continuity summaries, and workflow linkage.",
        },
        "workflows": {
            "path": str(root / "workflows"),
            "backup_priority": "critical",
            "preserve_on_restart": True,
            "mount_recommended": True,
            "regenerable": False,
            "description": "Workflow state, lineage, delegation contracts, synthesis, and audit metadata.",
        },
        "jobs": {
            "path": str(root / "jobs"),
            "backup_priority": "critical",
            "preserve_on_restart": True,
            "mount_recommended": True,
            "regenerable": False,
            "description": "Queued, scheduled, running, and terminal job state.",
        },
        "workers": {
            "path": str(root / "workers"),
            "backup_priority": "critical",
            "preserve_on_restart": True,
            "mount_recommended": True,
            "regenerable": False,
            "description": "Worker leases, assignments, and transition history.",
        },
        "memories": {
            "path": str(root / "memories"),
            "backup_priority": "critical",
            "preserve_on_restart": True,
            "mount_recommended": True,
            "regenerable": False,
            "description": "Typed memory records and continuity-support state.",
        },
        "artifacts": {
            "path": str(root / "artifacts"),
            "backup_priority": "recommended",
            "preserve_on_restart": True,
            "mount_recommended": True,
            "regenerable": False,
            "description": "Workflow and tool artifacts that may be expensive or impossible to rebuild exactly.",
        },
        "approvals": {
            "path": str(root / "approvals"),
            "backup_priority": "recommended",
            "preserve_on_restart": True,
            "mount_recommended": True,
            "regenerable": False,
            "description": "Approval requests and resume state for paused runs.",
        },
        "logs": {
            "path": str(root / "logs"),
            "backup_priority": "recommended",
            "preserve_on_restart": True,
            "mount_recommended": True,
            "regenerable": True,
            "description": "Trace and operational log output useful for incident review and audits.",
        },
    }


def storage_profile() -> dict[str, Any]:
    layout = storage_layout()
    return {
        "root": str(state_root()),
        "root_env_var": STATE_ROOT_ENV_VAR,
        "legacy_root_env_vars": [LEGACY_STATE_ROOT_ENV_VAR],
        "directories": layout,
        "guidance": {
            "must_preserve": [
                name for name, metadata in layout.items() if metadata["backup_priority"] == "critical"
            ],
            "should_preserve": [
                name for name, metadata in layout.items() if metadata["backup_priority"] == "recommended"
            ],
            "can_regenerate": [
                name for name, metadata in layout.items() if metadata["regenerable"]
            ],
            "packaged_mount_recommendation": (
                "Bind-mount the configured state root as one persistent directory in packaged deployments."
            ),
        },
    }
