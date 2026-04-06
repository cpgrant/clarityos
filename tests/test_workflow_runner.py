import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import runtime.approval as approval
import runtime.workflow as workflow
import runtime.workflow_runner as workflow_runner


class WorkflowRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.workflow_dir = self.root_dir / "workflows"
        self.approval_dir = self.root_dir / "approvals"
        self.workflow_dir.mkdir()
        self.approval_dir.mkdir()
        self.workflow_dir_patcher = patch.object(workflow, "WORKFLOW_DIR", self.workflow_dir)
        self.approval_dir_patcher = patch.object(approval, "APPROVAL_DIR", self.approval_dir)
        self.workflow_dir_patcher.start()
        self.approval_dir_patcher.start()

    def tearDown(self) -> None:
        self.workflow_dir_patcher.stop()
        self.approval_dir_patcher.stop()
        self.temp_dir.cleanup()

    def test_resume_waiting_workflow_uses_stored_request(self) -> None:
        state = workflow.create_workflow_state(
            run_id="wf-123",
            agent="default",
            run_type="tool",
            request={
                "input": "",
                "agent": "default",
                "tool": "echo",
                "tool_args": {"text": "hello"},
            },
        )
        approval_record = approval.create_approval(
            run_id="run-1",
            workflow_id=state.workflow_id,
            agent="default",
            policy_name="approval_exec",
            action={"capability": "exec", "tool": "echo", "command": "echo", "path": None},
            reason="needs approval",
            request=state.request,
        )
        workflow.wait_for_approval(state, approval_id=approval_record["approval_id"])
        workflow.write_workflow(state)

        with patch.object(workflow_runner, "run_agent", return_value={"status": "pending"}) as mock_run_agent:
            response = workflow_runner.resume_workflow(state.workflow_id)

        self.assertEqual(response["status"], "pending")
        mock_run_agent.assert_called_once_with(
            user_input="",
            agent_name="default",
            tool_name="echo",
            tool_args={"text": "hello"},
            approval_id=approval_record["approval_id"],
        )

    def test_resume_completed_workflow_raises(self) -> None:
        state = workflow.create_workflow_state(
            run_id="wf-123",
            agent="default",
            run_type="model",
            request={"input": "hello", "agent": "default", "tool": None, "tool_args": None},
        )
        workflow.complete_workflow(state)
        workflow.write_workflow(state)

        with self.assertRaisesRegex(ValueError, "Workflow `wf-123` has already succeeded"):
            workflow_runner.resume_workflow("wf-123")

    def test_start_child_workflow_registers_lineage(self) -> None:
        parent = workflow.create_workflow_state(
            run_id="wf-parent",
            agent="default",
            run_type="model",
            request={"input": "parent", "agent": "default", "tool": None, "tool_args": None},
        )
        workflow.configure_subrun_policy(parent, {"max_children": 1, "max_depth": 1})
        workflow.write_workflow(parent)

        with patch.object(
            workflow_runner,
            "run_agent",
            return_value={
                "status": "success",
                "workflow": {
                    "workflow_id": "wf-child",
                },
            },
        ) as mock_run_agent:
            response = workflow_runner.start_child_workflow(
                "wf-parent",
                user_input="child",
                agent_name="researcher",
                tool_name="echo",
                tool_args={"text": "hello"},
            )

        self.assertEqual(response["status"], "success")
        mock_run_agent.assert_called_once_with(
            user_input="child",
            agent_name="researcher",
            tool_name="echo",
            tool_args={"text": "hello"},
            parent_run_id="wf-parent",
            parent_workflow_id="wf-parent",
            root_workflow_id="wf-parent",
            workflow_depth=1,
        )
        reloaded_parent = workflow.load_workflow("wf-parent")
        self.assertEqual(reloaded_parent.child_workflow_ids, ["wf-child"])

    def test_start_child_workflow_enforces_bounds(self) -> None:
        parent = workflow.create_workflow_state(
            run_id="wf-parent",
            agent="default",
            run_type="model",
            request={"input": "parent", "agent": "default", "tool": None, "tool_args": None},
        )
        workflow.configure_subrun_policy(parent, {"max_children": 0, "max_depth": 0})
        workflow.write_workflow(parent)

        with self.assertRaisesRegex(ValueError, "Workflow `wf-parent` cannot spawn more child workflows"):
            workflow_runner.start_child_workflow(
                "wf-parent",
                user_input="child",
                agent_name="researcher",
            )

    def test_resume_retry_waiting_workflow_uses_stored_request(self) -> None:
        state = workflow.create_workflow_state(
            run_id="wf-123",
            agent="default",
            run_type="tool",
            request={
                "input": "",
                "agent": "default",
                "tool": "echo",
                "tool_args": {"text": "hello"},
            },
        )
        workflow.configure_retry_policy(state, {"max_attempts": 1, "backoff_seconds": 0})
        workflow.wait_for_retry(
            state,
            error_type="TimeoutError",
            message="transient timeout",
            retryable=True,
        )
        workflow.write_workflow(state)

        with patch.object(workflow_runner, "run_agent", return_value={"status": "success"}) as mock_run_agent:
            response = workflow_runner.resume_workflow(state.workflow_id)

        self.assertEqual(response["status"], "success")
        mock_run_agent.assert_called_once_with(
            user_input="",
            agent_name="default",
            tool_name="echo",
            tool_args={"text": "hello"},
            approval_id=None,
        )

    def test_resume_retry_waiting_workflow_before_backoff_raises(self) -> None:
        state = workflow.create_workflow_state(
            run_id="wf-123",
            agent="default",
            run_type="tool",
            request={
                "input": "",
                "agent": "default",
                "tool": "echo",
                "tool_args": {"text": "hello"},
            },
        )
        workflow.configure_retry_policy(state, {"max_attempts": 1, "backoff_seconds": 0})
        workflow.wait_for_retry(
            state,
            error_type="TimeoutError",
            message="transient timeout",
            retryable=True,
        )
        retry_step = workflow.current_step(state)
        retry_step.details["next_retry_at"] = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
        workflow.write_workflow(state)

        with self.assertRaisesRegex(ValueError, "Workflow `wf-123` is not ready to retry until"):
            workflow_runner.resume_workflow("wf-123")


if __name__ == "__main__":
    unittest.main()
