from datetime import datetime, timezone

from runtime.agent import run_agent
from runtime.approval import get_approval
from runtime.workflow import (
    can_spawn_child_workflow,
    current_step,
    load_workflow,
    register_child_workflow,
    write_workflow,
)


def start_workflow(
    *,
    user_input: str,
    agent_name: str,
    tool_name: str | None = None,
    tool_args: dict | None = None,
    approval_id: str | None = None,
) -> dict:
    return run_agent(
        user_input=user_input,
        agent_name=agent_name,
        tool_name=tool_name,
        tool_args=tool_args,
        approval_id=approval_id,
    )


def start_child_workflow(
    parent_workflow_id: str,
    *,
    user_input: str,
    agent_name: str,
    tool_name: str | None = None,
    tool_args: dict | None = None,
) -> dict:
    parent = load_workflow(parent_workflow_id)
    if not can_spawn_child_workflow(parent):
        raise ValueError(f"Workflow `{parent_workflow_id}` cannot spawn more child workflows")

    result = run_agent(
        user_input=user_input,
        agent_name=agent_name,
        tool_name=tool_name,
        tool_args=tool_args,
        parent_run_id=parent.latest_run_id,
        parent_workflow_id=parent.workflow_id,
        root_workflow_id=parent.root_workflow_id,
        workflow_depth=parent.depth + 1,
    )

    child_workflow_id = result["workflow"]["workflow_id"]
    register_child_workflow(parent, child_workflow_id=child_workflow_id)
    write_workflow(parent)
    return result


def workflow_request(workflow_id: str) -> dict:
    workflow = load_workflow(workflow_id)
    if workflow.request:
        return dict(workflow.request)

    step = current_step(workflow)
    if step.step_type == "approval_wait":
        approval = get_approval(step.details["approval_id"])
        return dict(approval["request"])

    raise ValueError(f"Workflow `{workflow_id}` does not have a stored request")


def resume_workflow(workflow_id: str) -> dict:
    workflow = load_workflow(workflow_id)
    if workflow.status == "succeeded":
        raise ValueError(f"Workflow `{workflow_id}` has already succeeded")
    if workflow.status == "failed":
        raise ValueError(f"Workflow `{workflow_id}` has already failed")

    request = workflow_request(workflow_id)

    approval_id = None
    step = current_step(workflow)
    if step.step_type == "approval_wait":
        approval_id = step.details["approval_id"]
    if step.step_type == "retry_wait":
        next_retry_at = step.details.get("next_retry_at")
        if next_retry_at is not None and datetime.now(timezone.utc) < datetime.fromisoformat(next_retry_at):
            raise ValueError(f"Workflow `{workflow_id}` is not ready to retry until {next_retry_at}")

    return run_agent(
        user_input=request.get("input", ""),
        agent_name=request.get("agent", workflow.agent),
        tool_name=request.get("tool"),
        tool_args=request.get("tool_args"),
        approval_id=approval_id,
    )
