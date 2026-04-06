import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from runtime.errors import ApprovalStateError


BASE_DIR = Path(__file__).resolve().parent.parent
APPROVAL_DIR = BASE_DIR / "approvals"

TRANSITIONS = {
    "pending": {"approved", "denied", "aborted"},
    "approved": {"resumed", "aborted"},
    "resumed": set(),
    "denied": set(),
    "aborted": set(),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def approval_path(approval_id: str) -> Path:
    return APPROVAL_DIR / f"{approval_id}.json"


def ensure_approval_dir() -> None:
    APPROVAL_DIR.mkdir(exist_ok=True)


def write_approval(approval: dict) -> dict:
    ensure_approval_dir()
    path = approval_path(approval["approval_id"])
    with path.open("w", encoding="utf-8") as file:
        json.dump(approval, file, indent=2)
    return approval


def get_approval(approval_id: str) -> dict:
    path = approval_path(approval_id)
    if not path.is_file():
        raise FileNotFoundError(f"Approval not found: {approval_id}")

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def add_history_entry(approval: dict, state: str, *, actor: str) -> None:
    approval["history"].append(
        {
            "state": state,
            "timestamp": utc_now(),
            "actor": actor,
        }
    )


def create_approval(
    *,
    run_id: str,
    agent: str,
    policy_name: str,
    action: dict,
    reason: str,
    request: dict,
) -> dict:
    timestamp = utc_now()
    approval = {
        "approval_id": str(uuid.uuid4()),
        "status": "pending",
        "created_at": timestamp,
        "updated_at": timestamp,
        "requested_run_id": run_id,
        "resumed_run_id": None,
        "agent": agent,
        "policy": policy_name,
        "action": action,
        "reason": reason,
        "request": request,
        "history": [
            {
                "state": "requested",
                "timestamp": timestamp,
                "actor": "system",
            },
            {
                "state": "pending",
                "timestamp": timestamp,
                "actor": "system",
            },
        ],
    }
    return write_approval(approval)


def update_approval_status(approval_id: str, status: str, *, actor: str) -> dict:
    approval = get_approval(approval_id)
    current_status = approval["status"]
    allowed_transitions = TRANSITIONS.get(current_status, set())
    if status not in allowed_transitions:
        raise ApprovalStateError(
            f"Cannot transition approval `{approval_id}` from `{current_status}` to `{status}`",
            approval_id=approval_id,
        )

    approval["status"] = status
    approval["updated_at"] = utc_now()
    add_history_entry(approval, status, actor=actor)
    return write_approval(approval)


def approve_approval(approval_id: str) -> dict:
    return update_approval_status(approval_id, "approved", actor="operator")


def deny_approval(approval_id: str) -> dict:
    return update_approval_status(approval_id, "denied", actor="operator")


def abort_approval(approval_id: str) -> dict:
    return update_approval_status(approval_id, "aborted", actor="operator")


def mark_approval_resumed(approval_id: str, *, resumed_run_id: str) -> dict:
    approval = update_approval_status(approval_id, "resumed", actor="system")
    approval["resumed_run_id"] = resumed_run_id
    approval["updated_at"] = utc_now()
    return write_approval(approval)


def approval_matches_request(
    approval: dict,
    *,
    user_input: str,
    agent_name: str,
    tool_name: str | None,
    tool_args: dict | None,
) -> bool:
    return approval["request"] == {
        "input": user_input,
        "agent": agent_name,
        "tool": tool_name,
        "tool_args": tool_args,
    }


def approval_summary(approval: dict) -> dict:
    return {
        "approval_id": approval["approval_id"],
        "status": approval["status"],
        "agent": approval["agent"],
        "policy": approval["policy"],
        "action": approval["action"],
        "reason": approval["reason"],
        "requested_run_id": approval["requested_run_id"],
        "resumed_run_id": approval["resumed_run_id"],
        "created_at": approval["created_at"],
        "updated_at": approval["updated_at"],
    }
