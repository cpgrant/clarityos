import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


WORKFLOW_STEP_TYPES = {"model", "tool", "approval_wait", "retry_wait", "finish"}
WORKFLOW_STATUSES = {"running", "waiting", "succeeded", "failed"}
STEP_STATUSES = {"pending", "in_progress", "blocked", "completed", "failed"}

WORKFLOW_STATUS_TRANSITIONS = {
    "running": {"waiting", "succeeded", "failed"},
    "waiting": {"running", "failed"},
    "succeeded": set(),
    "failed": set(),
}

STEP_STATUS_TRANSITIONS = {
    "pending": {"in_progress", "blocked", "completed", "failed"},
    "in_progress": {"blocked", "completed", "failed"},
    "blocked": {"in_progress", "completed", "failed"},
    "completed": set(),
    "failed": set(),
}

BASE_DIR = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = BASE_DIR / "workflows"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkflowStep:
    step_id: str
    step_type: str
    status: str
    details: dict = field(default_factory=dict)
    error: dict | None = None


@dataclass
class WorkflowState:
    workflow_id: str
    run_id: str
    latest_run_id: str
    root_workflow_id: str
    parent_workflow_id: str | None
    depth: int
    child_workflow_ids: list[str]
    agent: str
    run_type: str
    request: dict
    artifacts: list[dict]
    memories: list[dict]
    subrun_policy: dict
    retry_policy: dict
    retry_state: dict
    status: str
    current_step_id: str
    steps: list[WorkflowStep]
    created_at: str
    updated_at: str


def workflow_path(workflow_id: str) -> Path:
    return WORKFLOW_DIR / f"{workflow_id}.json"


def ensure_workflow_dir() -> None:
    WORKFLOW_DIR.mkdir(exist_ok=True)


def assert_valid_step_type(step_type: str) -> None:
    if step_type not in WORKFLOW_STEP_TYPES:
        raise ValueError(f"Unknown workflow step type: {step_type}")


def assert_valid_step_status(status: str) -> None:
    if status not in STEP_STATUSES:
        raise ValueError(f"Unknown workflow step status: {status}")


def assert_valid_workflow_status(status: str) -> None:
    if status not in WORKFLOW_STATUSES:
        raise ValueError(f"Unknown workflow status: {status}")


def action_step_id(run_type: str) -> str:
    return f"{run_type}_step"


def finish_step_id() -> str:
    return "finish_step"


def approval_step_id(approval_id: str) -> str:
    return f"approval_wait:{approval_id}"


def retry_step_id(attempt: int) -> str:
    return f"retry_wait:{attempt}"


def get_step(workflow: WorkflowState, step_id: str) -> WorkflowStep:
    for step in workflow.steps:
        if step.step_id == step_id:
            return step

    raise ValueError(f"Unknown workflow step: {step_id}")


def current_step(workflow: WorkflowState) -> WorkflowStep:
    return get_step(workflow, workflow.current_step_id)


def action_step(workflow: WorkflowState) -> WorkflowStep:
    return get_step(workflow, action_step_id(workflow.run_type))


def transition_step(step: WorkflowStep, next_status: str, *, error: dict | None = None) -> None:
    assert_valid_step_status(step.status)
    assert_valid_step_status(next_status)
    if next_status not in STEP_STATUS_TRANSITIONS[step.status]:
        raise ValueError(
            f"Cannot transition workflow step `{step.step_id}` from `{step.status}` to `{next_status}`"
        )

    step.status = next_status
    if error is not None:
        step.error = error


def transition_workflow(workflow: WorkflowState, next_status: str) -> None:
    assert_valid_workflow_status(workflow.status)
    assert_valid_workflow_status(next_status)
    if next_status not in WORKFLOW_STATUS_TRANSITIONS[workflow.status]:
        raise ValueError(
            f"Cannot transition workflow `{workflow.workflow_id}` from `{workflow.status}` to `{next_status}`"
        )

    workflow.status = next_status


def start_step(step: WorkflowStep) -> None:
    if step.status == "pending":
        transition_step(step, "in_progress")


def mark_action_completed(workflow: WorkflowState) -> None:
    action = action_step(workflow)
    if action.status != "completed":
        transition_step(action, "completed")

    finish = get_step(workflow, finish_step_id())
    start_step(finish)
    workflow.current_step_id = finish.step_id


def complete_finish_step(workflow: WorkflowState) -> None:
    finish = get_step(workflow, finish_step_id())
    start_step(finish)
    if finish.status != "completed":
        transition_step(finish, "completed")
    if workflow.status != "succeeded":
        transition_workflow(workflow, "succeeded")
    workflow.current_step_id = finish.step_id


def normalize_retry_policy(retry_policy: dict | None) -> dict:
    retry_policy = retry_policy or {}
    max_attempts = retry_policy.get("max_attempts", 0)
    backoff_seconds = retry_policy.get("backoff_seconds", 0)
    if not isinstance(max_attempts, int) or max_attempts < 0:
        raise ValueError("Workflow retry policy `max_attempts` must be a non-negative integer")
    if not isinstance(backoff_seconds, int) or backoff_seconds < 0:
        raise ValueError("Workflow retry policy `backoff_seconds` must be a non-negative integer")

    return {
        "max_attempts": max_attempts,
        "backoff_seconds": backoff_seconds,
    }


def default_retry_state(retry_policy: dict) -> dict:
    return {
        "attempts_used": 0,
        "retries_remaining": retry_policy["max_attempts"],
        "next_retry_at": None,
        "last_error": None,
    }


def normalize_subrun_policy(subrun_policy: dict | None) -> dict:
    subrun_policy = subrun_policy or {}
    max_children = subrun_policy.get("max_children", 0)
    max_depth = subrun_policy.get("max_depth", 0)
    if not isinstance(max_children, int) or max_children < 0:
        raise ValueError("Workflow subrun policy `max_children` must be a non-negative integer")
    if not isinstance(max_depth, int) or max_depth < 0:
        raise ValueError("Workflow subrun policy `max_depth` must be a non-negative integer")

    return {
        "max_children": max_children,
        "max_depth": max_depth,
    }


def create_workflow_state(
    *,
    run_id: str,
    agent: str,
    run_type: str,
    request: dict | None = None,
    parent_workflow_id: str | None = None,
    root_workflow_id: str | None = None,
    depth: int = 0,
) -> WorkflowState:
    assert_valid_step_type(run_type)
    if not isinstance(depth, int) or depth < 0:
        raise ValueError("Workflow depth must be a non-negative integer")

    action = WorkflowStep(
        step_id=action_step_id(run_type),
        step_type=run_type,
        status="in_progress",
    )
    finish = WorkflowStep(
        step_id=finish_step_id(),
        step_type="finish",
        status="pending",
    )
    timestamp = utc_now()

    return WorkflowState(
        workflow_id=run_id,
        run_id=run_id,
        latest_run_id=run_id,
        root_workflow_id=root_workflow_id or run_id,
        parent_workflow_id=parent_workflow_id,
        depth=depth,
        child_workflow_ids=[],
        agent=agent,
        run_type=run_type,
        request=dict(request or {}),
        artifacts=[],
        memories=[],
        subrun_policy=normalize_subrun_policy(None),
        retry_policy=normalize_retry_policy(None),
        retry_state=default_retry_state(normalize_retry_policy(None)),
        status="running",
        current_step_id=action.step_id,
        steps=[action, finish],
        created_at=timestamp,
        updated_at=timestamp,
    )


def attach_run_to_workflow(workflow: WorkflowState, *, run_id: str) -> None:
    workflow.latest_run_id = run_id


def set_action_details(workflow: WorkflowState, **details: object) -> None:
    action = action_step(workflow)
    action.details.update(details)


def configure_retry_policy(workflow: WorkflowState, retry_policy: dict | None) -> None:
    workflow.retry_policy = normalize_retry_policy(retry_policy)
    if not workflow.retry_state:
        workflow.retry_state = default_retry_state(workflow.retry_policy)
        return

    workflow.retry_state["retries_remaining"] = max(
        workflow.retry_policy["max_attempts"] - workflow.retry_state.get("attempts_used", 0),
        0,
    )


def configure_subrun_policy(workflow: WorkflowState, subrun_policy: dict | None) -> None:
    workflow.subrun_policy = normalize_subrun_policy(subrun_policy)


def register_artifact(workflow: WorkflowState, artifact: dict) -> None:
    artifact_id = artifact["artifact_id"]
    for existing in workflow.artifacts:
        if existing["artifact_id"] == artifact_id:
            return
    workflow.artifacts.append(dict(artifact))


def register_memory(workflow: WorkflowState, memory: dict) -> None:
    memory_id = memory["memory_id"]
    for index, existing in enumerate(workflow.memories):
        if existing["memory_id"] == memory_id:
            workflow.memories[index] = dict(memory)
            return
    workflow.memories.append(dict(memory))


def can_spawn_child_workflow(workflow: WorkflowState) -> bool:
    if workflow.depth >= workflow.subrun_policy["max_depth"]:
        return False
    return len(workflow.child_workflow_ids) < workflow.subrun_policy["max_children"]


def register_child_workflow(workflow: WorkflowState, *, child_workflow_id: str) -> None:
    if child_workflow_id in workflow.child_workflow_ids:
        return
    if not can_spawn_child_workflow(workflow):
        raise ValueError(f"Workflow `{workflow.workflow_id}` cannot spawn more child workflows")
    workflow.child_workflow_ids.append(child_workflow_id)


def can_retry(workflow: WorkflowState) -> bool:
    return workflow.retry_state.get("attempts_used", 0) < workflow.retry_policy["max_attempts"]


def wait_for_approval(
    workflow: WorkflowState,
    *,
    approval_id: str,
    details: dict | None = None,
) -> None:
    action = action_step(workflow)
    if action.status == "in_progress":
        transition_step(action, "blocked")

    step_id = approval_step_id(approval_id)
    try:
        approval = get_step(workflow, step_id)
    except ValueError:
        approval = WorkflowStep(
            step_id=step_id,
            step_type="approval_wait",
            status="in_progress",
            details={"approval_id": approval_id, **(details or {})},
        )
        workflow.steps.insert(-1, approval)
    else:
        approval.details.update(details or {})

    if workflow.status != "waiting":
        transition_workflow(workflow, "waiting")
    workflow.current_step_id = approval.step_id


def wait_for_retry(
    workflow: WorkflowState,
    *,
    error_type: str,
    message: str,
    retryable: bool,
) -> None:
    if not retryable:
        raise ValueError("Cannot schedule a retry for a terminal error")
    if not can_retry(workflow):
        raise ValueError(f"Workflow `{workflow.workflow_id}` has exhausted its retry budget")

    action = action_step(workflow)
    if action.status == "in_progress":
        transition_step(action, "blocked")

    attempt = workflow.retry_state.get("attempts_used", 0) + 1
    next_retry_at = (datetime.now(timezone.utc) + timedelta(seconds=workflow.retry_policy["backoff_seconds"])).isoformat()
    error = {
        "error_type": error_type,
        "message": message,
        "retryable": retryable,
    }

    step_id = retry_step_id(attempt)
    try:
        retry_step = get_step(workflow, step_id)
    except ValueError:
        retry_step = WorkflowStep(
            step_id=step_id,
            step_type="retry_wait",
            status="in_progress",
            details={
                "attempt": attempt,
                "next_retry_at": next_retry_at,
                "error": error,
            },
        )
        workflow.steps.insert(-1, retry_step)
    else:
        retry_step.details.update(
            {
                "attempt": attempt,
                "next_retry_at": next_retry_at,
                "error": error,
            }
        )

    workflow.retry_state = {
        "attempts_used": attempt,
        "retries_remaining": max(workflow.retry_policy["max_attempts"] - attempt, 0),
        "next_retry_at": next_retry_at,
        "last_error": error,
    }
    if workflow.status != "waiting":
        transition_workflow(workflow, "waiting")
    workflow.current_step_id = retry_step.step_id


def resume_from_approval(workflow: WorkflowState, *, approval_id: str) -> None:
    approval = get_step(workflow, approval_step_id(approval_id))
    if approval.status == "in_progress":
        transition_step(approval, "completed")

    if workflow.status == "waiting":
        transition_workflow(workflow, "running")

    action = action_step(workflow)
    if action.status == "blocked":
        transition_step(action, "in_progress")
    workflow.current_step_id = action.step_id


def resume_from_retry(workflow: WorkflowState) -> None:
    retry_step = current_step(workflow)
    if retry_step.step_type != "retry_wait":
        raise ValueError(f"Workflow `{workflow.workflow_id}` is not waiting on a retry step")

    if retry_step.status == "in_progress":
        transition_step(retry_step, "completed")

    if workflow.status == "waiting":
        transition_workflow(workflow, "running")

    action = action_step(workflow)
    if action.status == "blocked":
        transition_step(action, "in_progress")
    workflow.retry_state["next_retry_at"] = None
    workflow.current_step_id = action.step_id


def complete_workflow(workflow: WorkflowState) -> None:
    mark_action_completed(workflow)
    complete_finish_step(workflow)


def fail_workflow(workflow: WorkflowState, *, error_type: str, message: str) -> None:
    step = current_step(workflow)
    if step.status not in {"completed", "failed"}:
        transition_step(
            step,
            "failed",
            error={
                "error_type": error_type,
                "message": message,
            },
        )

    if workflow.status in {"waiting", "running"}:
        transition_workflow(workflow, "failed")


def workflow_snapshot(workflow: WorkflowState) -> dict:
    return {
        "workflow_id": workflow.workflow_id,
        "run_id": workflow.run_id,
        "latest_run_id": workflow.latest_run_id,
        "root_workflow_id": workflow.root_workflow_id,
        "parent_workflow_id": workflow.parent_workflow_id,
        "depth": workflow.depth,
        "child_workflow_ids": list(workflow.child_workflow_ids),
        "agent": workflow.agent,
        "run_type": workflow.run_type,
        "request": dict(workflow.request),
        "artifacts": [dict(artifact) for artifact in workflow.artifacts],
        "memories": [dict(memory) for memory in workflow.memories],
        "subrun_policy": dict(workflow.subrun_policy),
        "retry_policy": dict(workflow.retry_policy),
        "retry_state": {
            **workflow.retry_state,
            "last_error": (
                dict(workflow.retry_state["last_error"])
                if workflow.retry_state.get("last_error") is not None
                else None
            ),
        },
        "status": workflow.status,
        "current_step_id": workflow.current_step_id,
        "created_at": workflow.created_at,
        "updated_at": workflow.updated_at,
        "steps": [
            {
                "step_id": step.step_id,
                "step_type": step.step_type,
                "status": step.status,
                "details": dict(step.details),
                "error": dict(step.error) if step.error is not None else None,
            }
            for step in workflow.steps
        ],
    }


def write_workflow(workflow: WorkflowState) -> dict:
    ensure_workflow_dir()
    workflow.updated_at = utc_now()
    snapshot = workflow_snapshot(workflow)
    path = workflow_path(workflow.workflow_id)
    with path.open("w", encoding="utf-8") as file:
        json.dump(snapshot, file, indent=2)
    return snapshot


def load_workflow(workflow_id: str) -> WorkflowState:
    path = workflow_path(workflow_id)
    if not path.is_file():
        raise FileNotFoundError(f"Workflow not found: {workflow_id}")

    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    return WorkflowState(
        workflow_id=data["workflow_id"],
        run_id=data["run_id"],
        latest_run_id=data.get("latest_run_id", data["run_id"]),
        root_workflow_id=data.get("root_workflow_id", data["workflow_id"]),
        parent_workflow_id=data.get("parent_workflow_id"),
        depth=data.get("depth", 0),
        child_workflow_ids=data.get("child_workflow_ids", []),
        agent=data["agent"],
        run_type=data["run_type"],
        request=data.get("request", {}),
        artifacts=data.get("artifacts", []),
        memories=data.get("memories", []),
        subrun_policy=normalize_subrun_policy(data.get("subrun_policy")),
        retry_policy=normalize_retry_policy(data.get("retry_policy")),
        retry_state=data.get(
            "retry_state",
            default_retry_state(normalize_retry_policy(data.get("retry_policy"))),
        ),
        status=data["status"],
        current_step_id=data["current_step_id"],
        created_at=data.get("created_at", utc_now()),
        updated_at=data.get("updated_at", utc_now()),
        steps=[
            WorkflowStep(
                step_id=step["step_id"],
                step_type=step["step_type"],
                status=step["status"],
                details=step.get("details", {}),
                error=step.get("error"),
            )
            for step in data["steps"]
        ],
    )
