from runtime.approval import approval_summary, list_approvals_for_workflow
from runtime.artifact import artifact_summary, list_artifacts_for_workflow
from runtime.workflow import can_spawn_child_workflow, current_step, load_workflow, workflow_snapshot


def child_workflow_views(workflow) -> tuple[list[dict], list[str]]:
    children = []
    missing = []
    for child_workflow_id in workflow.child_workflow_ids:
        try:
            children.append(workflow_snapshot(load_workflow(child_workflow_id)))
        except FileNotFoundError:
            missing.append(child_workflow_id)

    return children, missing


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
    }


def workflow_control_view(workflow_id: str) -> dict:
    workflow = load_workflow(workflow_id)
    snapshot = workflow_snapshot(workflow)
    approvals = [approval_summary(approval) for approval in list_approvals_for_workflow(workflow_id)]
    artifacts = [
        artifact_summary(artifact)
        for artifact in list_artifacts_for_workflow(workflow_id)
    ]
    children, missing_child_workflow_ids = child_workflow_views(workflow)
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
        "child_workflows": children,
        "missing_child_workflow_ids": missing_child_workflow_ids,
        "actions": workflow_actions(workflow, approvals),
    }
