import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from runtime.approval import (
    approval_matches_request,
    approval_summary,
    create_approval,
    get_approval,
    mark_approval_resumed,
)
from runtime.budget import estimate_tokens, load_budget
from runtime.contracts import exception_from_tool_result
from runtime.errors import ApprovalStateError, PolicyDeniedError
from runtime.model import call_model
from runtime.policy import PolicyAction, build_agent_policy, evaluate_policy, snapshot_policy
from runtime.prompt_builder import build_prompt
from runtime.trace import trace_run
from runtime.tools import call_tool, get_tool_definition

BASE_DIR = Path(__file__).resolve().parent.parent
AGENTS_CONFIG_PATH = BASE_DIR / "config" / "agents.yaml"


@dataclass
class RunState:
    run_id: str
    run_type: str
    started_at: float
    parent_run_id: str | None = None
    prompt: str | None = None
    model_alias: str | None = None
    model_result: dict | None = None
    tool_output: Any = None
    tool_result: dict | None = None
    policy_name: str | None = None
    policy_snapshot: dict | None = None
    budget_limits: dict | None = None
    budget_used: dict | None = None
    approval_record: dict | None = None
    decision_log: list[dict] = field(default_factory=list)
    source_attribution: dict = field(
        default_factory=lambda: {
            "input": [],
            "context": [],
            "output": None,
        }
    )
    cost_accounting: dict = field(
        default_factory=lambda: {
            "estimated_tokens": {
                "input": 0,
                "context": 0,
                "output": 0,
                "total": 0,
            },
            "operations": {
                "model_calls": 0,
                "tool_calls": 0,
                "approvals_requested": 0,
                "approvals_resumed": 0,
            },
        }
    )


def load_agent(agent_name: str) -> dict:
    with AGENTS_CONFIG_PATH.open() as file:
        data = yaml.safe_load(file) or {}

    agents = data.get("agents", {})
    if agent_name not in agents:
        raise ValueError(f"Unknown agent: {agent_name}")

    return agents[agent_name]


def duration_ms(state: RunState) -> float:
    return round((time.perf_counter() - state.started_at) * 1000, 2)


def update_total_tokens(state: RunState) -> None:
    tokens = state.cost_accounting["estimated_tokens"]
    tokens["total"] = tokens["input"] + tokens["context"] + tokens["output"]


def append_input_source(
    state: RunState,
    source_type: str,
    *,
    token_estimate: int,
    **details: Any,
) -> None:
    state.source_attribution["input"].append(
        {
            "type": source_type,
            "token_estimate": token_estimate,
            **details,
        }
    )
    state.cost_accounting["estimated_tokens"]["input"] += token_estimate
    update_total_tokens(state)


def append_context_source(
    state: RunState,
    source_type: str,
    *,
    token_estimate: int,
    **details: Any,
) -> None:
    state.source_attribution["context"].append(
        {
            "type": source_type,
            "token_estimate": token_estimate,
            **details,
        }
    )
    state.cost_accounting["estimated_tokens"]["context"] += token_estimate
    update_total_tokens(state)


def set_output_source(
    state: RunState,
    source_type: str,
    *,
    token_estimate: int,
    **details: Any,
) -> None:
    state.source_attribution["output"] = {
        "type": source_type,
        "token_estimate": token_estimate,
        **details,
    }
    state.cost_accounting["estimated_tokens"]["output"] = token_estimate
    update_total_tokens(state)


def append_decision(
    state: RunState,
    *,
    stage: str,
    allowed: bool,
    requires_approval: bool,
    reason: str,
    target: dict,
    capability: str | None = None,
    matched_scope: str | None = None,
    approval_id: str | None = None,
) -> None:
    entry = {
        "stage": stage,
        "allowed": allowed,
        "requires_approval": requires_approval,
        "reason": reason,
        "target": target,
    }
    if capability is not None:
        entry["capability"] = capability
    if matched_scope is not None:
        entry["matched_scope"] = matched_scope
    if approval_id is not None:
        entry["approval_id"] = approval_id

    state.decision_log.append(entry)


def trace_payload_base(
    state: RunState,
    *,
    agent_name: str,
    user_input: str,
    status: str,
) -> dict:
    return {
        "run_id": state.run_id,
        "parent_run_id": state.parent_run_id,
        "run_type": state.run_type,
        "status": status,
        "duration_ms": duration_ms(state),
        "agent": agent_name,
        "policy_snapshot": state.policy_snapshot,
        "budget": {
            "limits": state.budget_limits,
            "used": state.budget_used,
        },
        "decision_log": state.decision_log,
        "source_attribution": state.source_attribution,
        "cost_accounting": state.cost_accounting,
        "context": {
            "input": user_input,
            "prompt": state.prompt,
            "model_alias": state.model_alias,
        },
    }


def approval_response(state: RunState, *, agent_name: str, tool_name: str | None, tool_args: dict | None) -> dict:
    return {
        "status": "pending",
        "run_type": state.run_type,
        "agent": agent_name,
        "policy": state.policy_name,
        "budget_limits": state.budget_limits,
        "budget_used": state.budget_used,
        "prompt": state.prompt,
        "provider": None,
        "model": state.model_alias if state.run_type == "model" else None,
        "tool": tool_name,
        "tool_args": tool_args,
        "tool_output": None,
        "tool_result": None,
        "approval": approval_summary(state.approval_record),
        "output": None,
    }


def success_response(state: RunState, *, agent_name: str) -> dict:
    if state.run_type == "tool":
        return {
            "status": "success",
            "run_type": state.run_type,
            "agent": agent_name,
            "policy": state.policy_name,
            "budget_limits": state.budget_limits,
            "budget_used": state.budget_used,
            "prompt": state.prompt,
            "provider": None,
            "model": None,
            "tool": state.tool_result["name"],
            "tool_args": state.tool_result["input"]["args"],
            "tool_output": state.tool_output,
            "tool_result": state.tool_result,
            "approval": (
                approval_summary(state.approval_record)
                if state.approval_record is not None
                else None
            ),
            "output": state.tool_output,
        }

    return {
        "status": "success",
        "run_type": state.run_type,
        "agent": agent_name,
        "policy": state.policy_name,
        "budget_limits": state.budget_limits,
        "budget_used": state.budget_used,
        "prompt": state.prompt,
        "provider": state.model_result["provider"],
        "model": state.model_result["model"],
        "tool": None,
        "tool_args": None,
        "tool_output": None,
        "tool_result": None,
        "approval": (
            approval_summary(state.approval_record)
            if state.approval_record is not None
            else None
        ),
        "output": state.model_result["output"],
    }


def tool_error_result(
    state: RunState,
    *,
    tool_name: str,
    tool_args: dict | None,
    exc: Exception,
) -> dict:
    return {
        "tool": {
            **(state.tool_result or {}),
            "name": tool_name,
            "ok": False,
            "input": (
                state.tool_result["input"]
                if state.tool_result is not None
                else {
                    "args": tool_args,
                }
            ),
            "output": None,
            "error": (
                state.tool_result["error"]
                if state.tool_result is not None and state.tool_result.get("error") is not None
                else {
                    "failure_type": "tool_error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "retryable": False,
                }
            ),
            "metadata": (
                state.tool_result["metadata"]
                if state.tool_result is not None and state.tool_result.get("metadata") is not None
                else {}
            ),
        },
        "output": state.tool_output,
        "error": {
            "error_type": type(exc).__name__,
            "message": str(exc),
        },
    }


def resolve_approval(
    state: RunState,
    *,
    approval_id: str | None,
    user_input: str,
    agent_name: str,
    tool_name: str | None,
    tool_args: dict | None,
    action: dict,
    reason: str,
) -> str:
    if approval_id is not None:
        state.approval_record = get_approval(approval_id)
        if not approval_matches_request(
            state.approval_record,
            user_input=user_input,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_args=tool_args,
        ):
            raise ValueError(f"Approval `{approval_id}` does not match the current request")

        if state.approval_record["status"] == "pending":
            append_decision(
                state,
                stage="approval_pending",
                allowed=False,
                requires_approval=True,
                reason=f"Approval `{approval_id}` is still pending",
                approval_id=approval_id,
                target=action,
            )
            state.cost_accounting["operations"]["approvals_requested"] += 1
            return "pending"

        if state.approval_record["status"] == "approved":
            state.approval_record = mark_approval_resumed(
                approval_id,
                resumed_run_id=state.run_id,
            )
            state.parent_run_id = state.approval_record["requested_run_id"]
            append_decision(
                state,
                stage="approval_resumed",
                allowed=True,
                requires_approval=False,
                reason=f"Approval `{approval_id}` was approved and resumed",
                approval_id=approval_id,
                target=action,
            )
            state.cost_accounting["operations"]["approvals_resumed"] += 1
            return "approved"

        if state.approval_record["status"] == "resumed":
            state.parent_run_id = state.approval_record["requested_run_id"]
            append_decision(
                state,
                stage="approval_resumed",
                allowed=True,
                requires_approval=False,
                reason=f"Approval `{approval_id}` was already resumed",
                approval_id=approval_id,
                target=action,
            )
            state.cost_accounting["operations"]["approvals_resumed"] += 1
            return "approved"

        if state.approval_record["status"] == "denied":
            raise PolicyDeniedError(
                f"Approval `{approval_id}` was denied",
                capability=action["capability"],
                policy_name=state.policy_name,
            )

        raise ApprovalStateError(
            f"Approval `{approval_id}` is `{state.approval_record['status']}` and cannot be resumed",
            approval_id=approval_id,
        )

    state.approval_record = create_approval(
        run_id=state.run_id,
        agent=agent_name,
        policy_name=state.policy_name,
        action=action,
        reason=reason,
        request={
            "input": user_input,
            "agent": agent_name,
            "tool": tool_name,
            "tool_args": tool_args,
        },
    )
    append_decision(
        state,
        stage="approval_requested",
        allowed=False,
        requires_approval=True,
        reason=reason,
        approval_id=state.approval_record["approval_id"],
        target=action,
    )
    state.cost_accounting["operations"]["approvals_requested"] += 1
    return "pending"


def finalize_pending_approval(
    state: RunState,
    *,
    budget: Any,
    agent_name: str,
    user_input: str,
    tool_name: str | None,
    tool_args: dict | None,
) -> dict:
    state.budget_used = budget.usage_snapshot()
    approval_tokens = estimate_tokens(approval_summary(state.approval_record))
    set_output_source(
        state,
        "approval",
        token_estimate=approval_tokens,
        approval_id=state.approval_record["approval_id"],
        status=state.approval_record["status"],
    )
    trace_run(
        {
            **trace_payload_base(state, agent_name=agent_name, user_input=user_input, status="pending"),
            "result": {
                "approval": approval_summary(state.approval_record),
                "output": None,
            },
        }
    )
    return approval_response(state, agent_name=agent_name, tool_name=tool_name, tool_args=tool_args)


def run_tool_path(
    state: RunState,
    *,
    budget: Any,
    policy: dict,
    agent_name: str,
    agent_config: dict,
    user_input: str,
    tool_name: str,
    tool_args: dict | None,
    approval_id: str | None,
) -> dict:
    allowed_tools = agent_config.get("tools", []) or []
    if tool_args is not None and not isinstance(tool_args, dict):
        raise ValueError("Tool arguments must be an object")

    append_input_source(
        state,
        "tool_args",
        token_estimate=estimate_tokens(tool_args or {}),
        tool=tool_name,
    )

    budget.consume_step()
    budget.consume_tool_call()

    if tool_name not in allowed_tools:
        raise ValueError(f"Tool not allowed for agent `{agent_name}`: {tool_name}")

    tool_definition = get_tool_definition(tool_name)
    action = PolicyAction(
        capability=tool_definition["capability"],
        path=(tool_args or {}).get(tool_definition.get("path_arg", "")),
        command=tool_definition.get("command"),
    )
    decision = evaluate_policy(policy, action)
    append_decision(
        state,
        stage="tool_policy_check",
        capability=action.capability,
        allowed=decision.allowed,
        requires_approval=decision.requires_approval,
        reason=decision.reason,
        matched_scope=decision.matched_scope,
        target={
            "tool": tool_name,
            "args": tool_args or {},
        },
    )

    if not decision.allowed:
        if decision.requires_approval:
            approval_status = resolve_approval(
                state,
                approval_id=approval_id,
                user_input=user_input,
                agent_name=agent_name,
                tool_name=tool_name,
                tool_args=tool_args,
                action={
                    "capability": action.capability,
                    "tool": tool_name,
                    "path": action.path,
                    "command": action.command,
                },
                reason=decision.reason,
            )
            if approval_status == "pending":
                return finalize_pending_approval(
                    state,
                    budget=budget,
                    agent_name=agent_name,
                    user_input=user_input,
                    tool_name=tool_name,
                    tool_args=tool_args,
                )
        else:
            raise PolicyDeniedError(
                decision.reason,
                capability=action.capability,
                policy_name=state.policy_name,
            )

    state.tool_result = call_tool(name=tool_name, args=tool_args)
    state.cost_accounting["operations"]["tool_calls"] += 1
    if not state.tool_result["ok"]:
        raise exception_from_tool_result(state.tool_result)

    state.tool_output = state.tool_result["output"]["value"]
    budget.consume_tokens(estimate_tokens(state.tool_output))
    budget.ensure_wall_clock_remaining()
    state.budget_used = budget.usage_snapshot()
    set_output_source(
        state,
        "tool",
        token_estimate=estimate_tokens(state.tool_output),
        tool=state.tool_result["name"],
    )

    trace_run(
        {
            **trace_payload_base(state, agent_name=agent_name, user_input=user_input, status="success"),
            "result": {
                "tool": state.tool_result,
                "output": state.tool_output,
            },
        }
    )
    return success_response(state, agent_name=agent_name)


def run_model_path(
    state: RunState,
    *,
    budget: Any,
    policy: dict,
    agent_name: str,
    agent_config: dict,
    user_input: str,
    approval_id: str | None,
) -> dict:
    budget.consume_step()
    state.prompt = build_prompt(user_input=user_input, config=agent_config)
    state.model_alias = agent_config["model"]

    append_context_source(
        state,
        "system_prompt",
        token_estimate=estimate_tokens(agent_config.get("system", "")),
    )
    append_context_source(
        state,
        "composed_prompt",
        token_estimate=estimate_tokens(state.prompt),
        model_alias=state.model_alias,
    )

    decision = evaluate_policy(
        policy,
        PolicyAction(
            capability="model_call",
            command=state.model_alias,
        ),
    )
    append_decision(
        state,
        stage="model_policy_check",
        capability="model_call",
        allowed=decision.allowed,
        requires_approval=decision.requires_approval,
        reason=decision.reason,
        matched_scope=decision.matched_scope,
        target={
            "model_alias": state.model_alias,
        },
    )

    if not decision.allowed:
        if decision.requires_approval:
            approval_status = resolve_approval(
                state,
                approval_id=approval_id,
                user_input=user_input,
                agent_name=agent_name,
                tool_name=None,
                tool_args=None,
                action={
                    "capability": "model_call",
                    "model_alias": state.model_alias,
                    "command": state.model_alias,
                },
                reason=decision.reason,
            )
            if approval_status == "pending":
                return finalize_pending_approval(
                    state,
                    budget=budget,
                    agent_name=agent_name,
                    user_input=user_input,
                    tool_name=None,
                    tool_args=None,
                )
        else:
            raise PolicyDeniedError(
                decision.reason,
                capability="model_call",
                policy_name=state.policy_name,
            )

    budget.consume_tokens(estimate_tokens(state.prompt))
    state.model_result = call_model(model_name=state.model_alias, prompt=state.prompt)
    state.cost_accounting["operations"]["model_calls"] += 1
    budget.consume_tokens(estimate_tokens(state.model_result["output"]))
    budget.ensure_wall_clock_remaining()
    state.budget_used = budget.usage_snapshot()
    set_output_source(
        state,
        "model",
        token_estimate=estimate_tokens(state.model_result["output"]),
        provider=state.model_result["provider"],
        model=state.model_result["model"],
    )

    trace_run(
        {
            **trace_payload_base(state, agent_name=agent_name, user_input=user_input, status="success"),
            "result": {
                "model": {
                    "provider": state.model_result["provider"],
                    "model": state.model_result["model"],
                },
                "output": state.model_result["output"],
            },
        }
    )
    return success_response(state, agent_name=agent_name)


def run_agent(
    user_input: str,
    agent_name: str,
    tool_name: str | None = None,
    tool_args: dict | None = None,
    approval_id: str | None = None,
) -> dict:
    state = RunState(
        run_id=str(uuid.uuid4()),
        run_type="tool" if tool_name is not None else "model",
        started_at=time.perf_counter(),
    )

    try:
        agent_config = load_agent(agent_name)
        policy = build_agent_policy(agent_config)
        state.policy_name = policy["name"]
        state.policy_snapshot = snapshot_policy(policy)
        budget = load_budget(agent_config.get("budgets"))
        state.budget_limits = budget.limits_snapshot()

        append_input_source(
            state,
            "user_input",
            token_estimate=estimate_tokens(user_input),
            source="request",
        )

        if tool_name is not None:
            return run_tool_path(
                state,
                budget=budget,
                policy=policy,
                agent_name=agent_name,
                agent_config=agent_config,
                user_input=user_input,
                tool_name=tool_name,
                tool_args=tool_args,
                approval_id=approval_id,
            )

        return run_model_path(
            state,
            budget=budget,
            policy=policy,
            agent_name=agent_name,
            agent_config=agent_config,
            user_input=user_input,
            approval_id=approval_id,
        )
    except Exception as exc:
        if "budget" in locals():
            state.budget_used = budget.usage_snapshot()

        trace_payload = {
            **trace_payload_base(state, agent_name=agent_name, user_input=user_input, status="error"),
            "result": {
                "error": {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            },
        }
        if tool_name is not None:
            trace_payload["result"] = tool_error_result(
                state,
                tool_name=tool_name,
                tool_args=tool_args,
                exc=exc,
            )

        trace_run(trace_payload)
        raise
