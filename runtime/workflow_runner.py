import uuid
from datetime import datetime, timezone

from runtime.agent import run_agent
from runtime.approval import get_approval
from runtime.errors import DelegationDeniedError
from runtime.memory import load_memory, memory_summary
from runtime.policy import assert_valid_capability
from runtime.tools import get_tool_definition
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
    job_id: str | None = None,
    worker_id: str | None = None,
    prompt_context: list[dict] | None = None,
) -> dict:
    return run_agent(
        user_input=user_input,
        agent_name=agent_name,
        tool_name=tool_name,
        tool_args=tool_args,
        approval_id=approval_id,
        job_id=job_id,
        worker_id=worker_id,
        prompt_context=prompt_context,
    )


def normalize_string_list(value: object, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Workflow `{field_name}` must be a list of strings")

    normalized = []
    seen = set()
    for raw_item in value:
        if not isinstance(raw_item, str) or not raw_item.strip():
            raise ValueError(f"Workflow `{field_name}` must contain non-empty strings")
        item = raw_item.strip()
        if item in seen:
            continue
        normalized.append(item)
        seen.add(item)
    return normalized


def normalize_role(role: object, *, agent_name: str) -> str:
    if role is None:
        return agent_name
    if not isinstance(role, str) or not role.strip():
        raise ValueError("Workflow `role` must be a non-empty string")
    return role.strip()


def normalize_memory_ids(shared_memory_ids: object) -> list[str]:
    return normalize_string_list(shared_memory_ids, field_name="shared_memory_ids")


def requested_capability(tool_name: str | None) -> str:
    if tool_name is None:
        return "model_call"
    return get_tool_definition(tool_name)["capability"]


def ensure_requested_agent_allowed(parent, agent_name: str) -> None:
    allowed_agents = parent.subrun_policy.get("allowed_agents")
    if allowed_agents is not None and agent_name not in allowed_agents:
        raise DelegationDeniedError(
            f"Workflow `{parent.workflow_id}` delegation does not allow agent `{agent_name}`",
            capability="workflow_subrun",
            workflow_id=parent.workflow_id,
        )


def ensure_subset(
    values: list[str],
    *,
    allowed_values: list[str] | None,
    field_name: str,
    parent_workflow_id: str,
) -> None:
    if allowed_values is None:
        return
    disallowed = sorted(set(values) - set(allowed_values))
    if not disallowed:
        return
    raise DelegationDeniedError(
        f"Workflow `{parent_workflow_id}` delegation does not allow {field_name}: {', '.join(disallowed)}",
        capability="workflow_subrun",
        workflow_id=parent_workflow_id,
    )


def build_child_delegation(
    parent,
    *,
    agent_name: str,
    tool_name: str | None,
    role: object,
    allowed_capabilities: object,
    allowed_tools: object,
) -> dict:
    ensure_requested_agent_allowed(parent, agent_name)

    capability = requested_capability(tool_name)
    child_allowed_capabilities = normalize_string_list(
        allowed_capabilities,
        field_name="allowed_capabilities",
    )
    if not child_allowed_capabilities:
        child_allowed_capabilities = [capability]
    for allowed_capability in child_allowed_capabilities:
        assert_valid_capability(allowed_capability)
    if capability not in child_allowed_capabilities:
        raise ValueError(
            f"Workflow child delegation must allow the requested capability `{capability}`"
        )

    child_allowed_tools = normalize_string_list(allowed_tools, field_name="allowed_tools")
    if tool_name is None:
        if child_allowed_tools:
            raise ValueError("Model child workflows cannot declare `allowed_tools`")
    else:
        if not child_allowed_tools:
            child_allowed_tools = [tool_name]
        if tool_name not in child_allowed_tools:
            raise ValueError(f"Workflow child delegation must allow the requested tool `{tool_name}`")

    ensure_subset(
        child_allowed_capabilities,
        allowed_values=parent.subrun_policy.get("allowed_capabilities"),
        field_name="capabilities",
        parent_workflow_id=parent.workflow_id,
    )
    if tool_name is not None:
        ensure_subset(
            child_allowed_tools,
            allowed_values=parent.subrun_policy.get("allowed_tools"),
            field_name="tools",
            parent_workflow_id=parent.workflow_id,
        )

    return {
        "role": normalize_role(role, agent_name=agent_name),
        "assigned_by_workflow_id": parent.workflow_id,
        "assigned_by_run_id": parent.latest_run_id,
        "allowed_capabilities": child_allowed_capabilities,
        "allowed_tools": child_allowed_tools,
    }


def memory_is_shareable_with_child(parent, memory_record: dict, *, child_agent_name: str) -> bool:
    scope = memory_record.get("scope", {})
    kind = scope.get("kind")
    value = scope.get("value")
    if kind == "global":
        return True
    if kind == "agent":
        return value in {parent.agent, child_agent_name}
    if kind == "workflow":
        return value in {parent.workflow_id, parent.root_workflow_id}
    if kind == "run":
        return value in {parent.run_id, parent.latest_run_id}
    return False


def materialize_shared_memories(parent, *, child_agent_name: str, shared_memory_ids: object) -> list[dict]:
    shared_memories = []
    for memory_id in normalize_memory_ids(shared_memory_ids):
        memory_record = load_memory(memory_id)
        if not memory_is_shareable_with_child(parent, memory_record, child_agent_name=child_agent_name):
            raise DelegationDeniedError(
                f"Workflow `{parent.workflow_id}` cannot hand off memory `{memory_id}` to agent `{child_agent_name}`",
                capability="memory_read",
                workflow_id=parent.workflow_id,
            )
        shared_memories.append(memory_summary(memory_record))
    return shared_memories


def start_child_workflow(
    parent_workflow_id: str,
    *,
    user_input: str,
    agent_name: str,
    tool_name: str | None = None,
    tool_args: dict | None = None,
    role: str | None = None,
    allowed_capabilities: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    shared_memory_ids: list[str] | None = None,
    job_id: str | None = None,
    worker_id: str | None = None,
) -> dict:
    parent = load_workflow(parent_workflow_id)
    if not can_spawn_child_workflow(parent):
        raise ValueError(f"Workflow `{parent_workflow_id}` cannot spawn more child workflows")
    delegation = build_child_delegation(
        parent,
        agent_name=agent_name,
        tool_name=tool_name,
        role=role,
        allowed_capabilities=allowed_capabilities,
        allowed_tools=allowed_tools,
    )
    shared_memories = materialize_shared_memories(
        parent,
        child_agent_name=agent_name,
        shared_memory_ids=shared_memory_ids,
    )
    child_workflow_id = str(uuid.uuid4())

    try:
        result = run_agent(
            user_input=user_input,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_args=tool_args,
            run_id=child_workflow_id,
            parent_run_id=parent.latest_run_id,
            parent_workflow_id=parent.workflow_id,
            root_workflow_id=parent.root_workflow_id,
            workflow_depth=parent.depth + 1,
            job_id=job_id,
            worker_id=worker_id,
            delegation=delegation,
            shared_memories=shared_memories,
        )
    except Exception:
        register_child_workflow(parent, child_workflow_id=child_workflow_id)
        write_workflow(parent)
        raise

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


def resume_workflow(workflow_id: str, *, job_id: str | None = None, worker_id: str | None = None) -> dict:
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
        job_id=job_id,
        worker_id=worker_id,
    )


def safe_resume_workflow(workflow_id: str, *, job_id: str | None = None, worker_id: str | None = None) -> dict:
    workflow = load_workflow(workflow_id)
    if workflow.status != "waiting":
        raise ValueError(f"Workflow `{workflow_id}` is not waiting and cannot be safely resumed")

    step = current_step(workflow)
    if step.step_type not in {"approval_wait", "retry_wait"}:
        raise ValueError(
            f"Workflow `{workflow_id}` is waiting on unsupported step type `{step.step_type}`"
        )

    return resume_workflow(workflow_id, job_id=job_id, worker_id=worker_id)


def replay_workflow(workflow_id: str, *, job_id: str | None = None, worker_id: str | None = None) -> dict:
    workflow = load_workflow(workflow_id)
    if workflow.status != "failed":
        raise ValueError(f"Workflow `{workflow_id}` must be failed before it can be replayed")

    request = workflow_request(workflow_id)
    result = run_agent(
        user_input=request.get("input", ""),
        agent_name=request.get("agent", workflow.agent),
        tool_name=request.get("tool"),
        tool_args=request.get("tool_args"),
        job_id=job_id,
        worker_id=worker_id,
    )
    return {
        "replayed_from_workflow_id": workflow_id,
        "source_status": workflow.status,
        "result": result,
    }
