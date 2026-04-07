from runtime.approval import approval_summary, list_approvals_for_workflow
from runtime.artifact import artifact_summary, list_artifacts_for_workflow
from runtime.memory import memory_summary
from runtime.workflow import can_spawn_child_workflow, current_step, load_workflow, workflow_snapshot


def workflow_failure_view(workflow) -> dict | None:
    if workflow.status != "failed":
        return None

    step = current_step(workflow)
    error = dict(step.error) if step.error is not None else None
    if error is None:
        for candidate in reversed(workflow.steps):
            if candidate.error is not None:
                error = dict(candidate.error)
                break

    return {
        "workflow_id": workflow.workflow_id,
        "step_id": step.step_id,
        "step_type": step.step_type,
        "error": error,
        "path": f"/workflows/{workflow.workflow_id}",
    }


def child_workflow_view(workflow) -> dict:
    step = current_step(workflow)
    return {
        **workflow_snapshot(workflow),
        "path": f"/workflows/{workflow.workflow_id}",
        "current_step": {
            "step_id": step.step_id,
            "step_type": step.step_type,
            "status": step.status,
            "details": dict(step.details),
            "error": dict(step.error) if step.error is not None else None,
        },
        "failure": workflow_failure_view(workflow),
    }


def child_workflow_views(workflow) -> tuple[list[dict], list[str]]:
    children = []
    missing = []
    for child_workflow_id in workflow.child_workflow_ids:
        try:
            children.append(child_workflow_view(load_workflow(child_workflow_id)))
        except FileNotFoundError:
            missing.append(child_workflow_id)

    return children, missing


def child_workflow_summary(workflow, children: list[dict], missing_child_workflow_ids: list[str]) -> dict:
    status_counts = {
        "running": 0,
        "waiting": 0,
        "succeeded": 0,
        "failed": 0,
        "missing": len(missing_child_workflow_ids),
    }
    failed_children = []
    for child in children:
        status = child["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        if child.get("failure") is not None:
            failed_children.append(
                {
                    "workflow_id": child["workflow_id"],
                    "agent": child["agent"],
                    "role": child.get("delegation", {}).get("role"),
                    "path": child["path"],
                    "error": dict(child["failure"]["error"]) if child["failure"]["error"] is not None else None,
                    "step_id": child["failure"]["step_id"],
                    "step_type": child["failure"]["step_type"],
                    "isolated_from_parent": workflow.status != "failed",
                }
            )

    isolation_state = "clear"
    if failed_children and workflow.status != "failed":
        isolation_state = "contained"
    elif failed_children and workflow.status == "failed":
        isolation_state = "parent_failed"

    return {
        "status_counts": status_counts,
        "failed_children": failed_children,
        "missing_child_workflow_ids": list(missing_child_workflow_ids),
        "isolation_state": isolation_state,
        "parent_status": workflow.status,
    }


def workflow_actions(workflow, approvals: list[dict]) -> dict:
    step = current_step(workflow)
    pending_approvals = [approval for approval in approvals if approval["status"] == "pending"]

    return {
        "resume": {
            "available": workflow.status == "waiting",
            "path": f"/workflows/{workflow.workflow_id}/resume",
            "step_type": step.step_type,
        },
        "spawn_subrun": {
            "available": can_spawn_child_workflow(workflow),
            "path": f"/workflows/{workflow.workflow_id}/subruns",
            "remaining_children": max(
                workflow.subrun_policy["max_children"] - len(workflow.child_workflow_ids),
                0,
            ),
            "max_depth": workflow.subrun_policy["max_depth"],
        },
        "approvals": [
            {
                "approval_id": approval["approval_id"],
                "approve_path": f"/approvals/{approval['approval_id']}/approve",
                "deny_path": f"/approvals/{approval['approval_id']}/deny",
                "abort_path": f"/approvals/{approval['approval_id']}/abort",
            }
            for approval in pending_approvals
        ],
        "artifacts": [
            {
                "artifact_id": artifact["artifact_id"],
                "path": f"/artifacts/{artifact['artifact_id']}",
            }
            for artifact in workflow.artifacts
        ],
        "memories": [
            {
                "memory_id": memory["memory_id"],
                "artifact_id": memory.get("artifact_id"),
            }
            for memory in workflow.memories
        ],
        "child_workflows": [
            {
                "workflow_id": child_workflow_id,
                "path": f"/workflows/{child_workflow_id}",
            }
            for child_workflow_id in workflow.child_workflow_ids
        ],
    }


def workflow_control_view(workflow_id: str) -> dict:
    workflow = load_workflow(workflow_id)
    snapshot = workflow_snapshot(workflow)
    approvals = [approval_summary(approval) for approval in list_approvals_for_workflow(workflow_id)]
    artifacts = [
        artifact_summary(artifact)
        for artifact in list_artifacts_for_workflow(workflow_id)
    ]
    memories = [memory_summary(memory) for memory in workflow.memories]
    children, missing_child_workflow_ids = child_workflow_views(workflow)
    child_summary = child_workflow_summary(workflow, children, missing_child_workflow_ids)
    step = current_step(workflow)

    return {
        **snapshot,
        "current_step": {
            "step_id": step.step_id,
            "step_type": step.step_type,
            "status": step.status,
            "details": dict(step.details),
            "error": dict(step.error) if step.error is not None else None,
        },
        "approvals": approvals,
        "artifacts": artifacts,
        "memories": memories,
        "shared_memories": [dict(memory) for memory in workflow.shared_memories],
        "child_workflows": children,
        "child_summary": child_summary,
        "failure": workflow_failure_view(workflow),
        "missing_child_workflow_ids": missing_child_workflow_ids,
        "actions": workflow_actions(workflow, approvals),
    }
