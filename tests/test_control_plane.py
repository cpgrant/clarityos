import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime.approval as approval
import runtime.artifact as artifact
import runtime.memory as memory
import runtime.workflow as workflow
from runtime.control_plane import workflow_control_view


class ControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.approval_dir = self.root_dir / "approvals"
        self.artifact_dir = self.root_dir / "artifacts"
        self.memory_dir = self.root_dir / "memories"
        self.workflow_dir = self.root_dir / "workflows"
        self.approval_dir.mkdir()
        self.artifact_dir.mkdir()
        self.memory_dir.mkdir()
        self.workflow_dir.mkdir()
        self.approval_dir_patcher = patch.object(approval, "APPROVAL_DIR", self.approval_dir)
        self.artifact_dir_patcher = patch.object(artifact, "ARTIFACT_DIR", self.artifact_dir)
        self.memory_dir_patcher = patch.object(memory, "MEMORY_DIR", self.memory_dir)
        self.workflow_dir_patcher = patch.object(workflow, "WORKFLOW_DIR", self.workflow_dir)
        self.approval_dir_patcher.start()
        self.artifact_dir_patcher.start()
        self.memory_dir_patcher.start()
        self.workflow_dir_patcher.start()

    def tearDown(self) -> None:
        self.approval_dir_patcher.stop()
        self.artifact_dir_patcher.stop()
        self.memory_dir_patcher.stop()
        self.workflow_dir_patcher.stop()
        self.temp_dir.cleanup()

    def test_workflow_control_view_aggregates_related_state(self) -> None:
        parent = workflow.create_workflow_state(
            run_id="wf-parent",
            agent="default",
            run_type="tool",
            request={
                "input": "",
                "agent": "default",
                "tool": "echo",
                "tool_args": {"text": "hello"},
            },
        )
        workflow.configure_subrun_policy(parent, {"max_children": 2, "max_depth": 2})
        approval_record = approval.create_approval(
            run_id="run-1",
            workflow_id=parent.workflow_id,
            agent="default",
            policy_name="approval_exec",
            action={"capability": "exec", "tool": "echo", "command": "echo", "path": None},
            reason="needs approval",
            request=parent.request,
        )
        workflow.wait_for_approval(parent, approval_id=approval_record["approval_id"])
        saved_artifact = artifact.create_artifact(
            workflow_id=parent.workflow_id,
            run_id="run-1",
            name="result",
            kind="tool_output",
            value="hello",
            metadata={"tool": "echo"},
        )
        workflow.register_artifact(parent, artifact.artifact_summary(saved_artifact))
        saved_memory = memory.create_memory(
            memory_type="artifact_ref",
            scope_kind="workflow",
            workflow_id=parent.workflow_id,
            run_id="run-1",
            agent="default",
            payload={"artifact_id": saved_artifact["artifact_id"], "description": "result memory"},
            tags=["artifact"],
        )
        workflow.register_memory(parent, memory.memory_summary(saved_memory))
        child = workflow.create_workflow_state(
            run_id="wf-child",
            agent="researcher",
            run_type="model",
            parent_workflow_id=parent.workflow_id,
            root_workflow_id=parent.workflow_id,
            depth=1,
            delegation={
                "role": "summarizer",
                "assigned_by_workflow_id": parent.workflow_id,
                "assigned_by_run_id": parent.workflow_id,
                "allowed_capabilities": ["model_call"],
                "allowed_tools": [],
            },
            shared_memories=[memory.memory_summary(saved_memory)],
        )
        workflow.write_workflow(child)
        workflow.register_child_workflow(parent, child_workflow_id=child.workflow_id)
        workflow.write_workflow(parent)

        view = workflow_control_view(parent.workflow_id)

        self.assertEqual(view["workflow_id"], "wf-parent")
        self.assertEqual(view["current_step"]["step_type"], "approval_wait")
        self.assertEqual(len(view["approvals"]), 1)
        self.assertEqual(view["approvals"][0]["approval_id"], approval_record["approval_id"])
        self.assertEqual(len(view["artifacts"]), 1)
        self.assertEqual(view["artifacts"][0]["artifact_id"], saved_artifact["artifact_id"])
        self.assertEqual(len(view["memories"]), 1)
        self.assertEqual(view["memories"][0]["memory_id"], saved_memory["memory_id"])
        self.assertEqual(view["memories"][0]["artifact_id"], saved_artifact["artifact_id"])
        self.assertEqual(len(view["child_workflows"]), 1)
        self.assertEqual(view["child_workflows"][0]["workflow_id"], "wf-child")
        self.assertEqual(view["child_workflows"][0]["delegation"]["role"], "summarizer")
        self.assertEqual(view["child_workflows"][0]["shared_memories"][0]["memory_id"], saved_memory["memory_id"])
        self.assertEqual(view["actions"]["resume"]["available"], True)
        self.assertEqual(view["actions"]["approvals"][0]["approve_path"], f"/approvals/{approval_record['approval_id']}/approve")
        self.assertEqual(view["actions"]["artifacts"][0]["path"], f"/artifacts/{saved_artifact['artifact_id']}")
        self.assertEqual(view["actions"]["memories"][0]["memory_id"], saved_memory["memory_id"])

    def test_workflow_control_view_reports_child_failure_isolation(self) -> None:
        parent = workflow.create_workflow_state(
            run_id="wf-parent",
            agent="default",
            run_type="model",
        )
        workflow.configure_subrun_policy(parent, {"max_children": 2, "max_depth": 2})

        failed_child = workflow.create_workflow_state(
            run_id="wf-child-failed",
            agent="researcher",
            run_type="model",
            parent_workflow_id=parent.workflow_id,
            root_workflow_id=parent.workflow_id,
            depth=1,
            delegation={
                "role": "researcher",
                "assigned_by_workflow_id": parent.workflow_id,
                "assigned_by_run_id": parent.workflow_id,
                "allowed_capabilities": ["model_call"],
                "allowed_tools": [],
            },
        )
        workflow.fail_workflow(failed_child, error_type="RuntimeError", message="child exploded")
        workflow.write_workflow(failed_child)

        succeeded_child = workflow.create_workflow_state(
            run_id="wf-child-ok",
            agent="researcher",
            run_type="model",
            parent_workflow_id=parent.workflow_id,
            root_workflow_id=parent.workflow_id,
            depth=1,
            delegation={
                "role": "summarizer",
                "assigned_by_workflow_id": parent.workflow_id,
                "assigned_by_run_id": parent.workflow_id,
                "allowed_capabilities": ["model_call"],
                "allowed_tools": [],
            },
        )
        workflow.complete_workflow(succeeded_child)
        workflow.write_workflow(succeeded_child)

        workflow.register_child_workflow(parent, child_workflow_id=failed_child.workflow_id)
        workflow.register_child_workflow(parent, child_workflow_id=succeeded_child.workflow_id)
        workflow.write_workflow(parent)

        view = workflow_control_view(parent.workflow_id)

        self.assertEqual(view["child_summary"]["status_counts"]["failed"], 1)
        self.assertEqual(view["child_summary"]["status_counts"]["succeeded"], 1)
        self.assertEqual(view["child_summary"]["isolation_state"], "contained")
        self.assertEqual(view["child_summary"]["failed_children"][0]["workflow_id"], "wf-child-failed")
        self.assertTrue(view["child_summary"]["failed_children"][0]["isolated_from_parent"])
        self.assertEqual(view["child_workflows"][0]["path"], "/workflows/wf-child-failed")
        self.assertEqual(view["child_workflows"][0]["failure"]["error"]["message"], "child exploded")
        self.assertEqual(view["actions"]["child_workflows"][0]["path"], "/workflows/wf-child-failed")
        self.assertIsNone(view["failure"])


if __name__ == "__main__":
    unittest.main()
