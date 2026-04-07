import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import runtime.approval as approval
import runtime.memory as memory
import runtime.workflow as workflow
import runtime.workflow_runner as workflow_runner


class WorkflowRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.workflow_dir = self.root_dir / "workflows"
        self.approval_dir = self.root_dir / "approvals"
        self.memory_dir = self.root_dir / "memories"
        self.workflow_dir.mkdir()
        self.approval_dir.mkdir()
        self.memory_dir.mkdir()
        self.workflow_dir_patcher = patch.object(workflow, "WORKFLOW_DIR", self.workflow_dir)
        self.approval_dir_patcher = patch.object(approval, "APPROVAL_DIR", self.approval_dir)
        self.memory_dir_patcher = patch.object(memory, "MEMORY_DIR", self.memory_dir)
        self.workflow_dir_patcher.start()
        self.approval_dir_patcher.start()
        self.memory_dir_patcher.start()

    def tearDown(self) -> None:
        self.workflow_dir_patcher.stop()
        self.approval_dir_patcher.stop()
        self.memory_dir_patcher.stop()
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
        workflow.configure_subrun_policy(
            parent,
            {
                "max_children": 1,
                "max_depth": 1,
                "allowed_agents": ["researcher"],
                "allowed_capabilities": ["exec"],
                "allowed_tools": ["echo"],
            },
        )
        workflow.write_workflow(parent)

        with patch.object(
            workflow_runner,
            "run_agent",
            side_effect=lambda **kwargs: {
                "status": "success",
                "workflow": {
                    "workflow_id": kwargs["run_id"],
                },
            },
        ) as mock_run_agent:
            response = workflow_runner.start_child_workflow(
                "wf-parent",
                user_input="child",
                agent_name="researcher",
                tool_name="echo",
                tool_args={"text": "hello"},
                role="summarizer",
                allowed_capabilities=["exec"],
                allowed_tools=["echo"],
            )

        self.assertEqual(response["status"], "success")
        mock_run_agent.assert_called_once()
        self.assertEqual(mock_run_agent.call_args.kwargs["user_input"], "child")
        self.assertEqual(mock_run_agent.call_args.kwargs["agent_name"], "researcher")
        self.assertEqual(mock_run_agent.call_args.kwargs["tool_name"], "echo")
        self.assertEqual(mock_run_agent.call_args.kwargs["tool_args"], {"text": "hello"})
        self.assertIsInstance(mock_run_agent.call_args.kwargs["run_id"], str)
        self.assertEqual(mock_run_agent.call_args.kwargs["parent_run_id"], "wf-parent")
        self.assertEqual(mock_run_agent.call_args.kwargs["parent_workflow_id"], "wf-parent")
        self.assertEqual(mock_run_agent.call_args.kwargs["root_workflow_id"], "wf-parent")
        self.assertEqual(mock_run_agent.call_args.kwargs["workflow_depth"], 1)
        self.assertEqual(
            mock_run_agent.call_args.kwargs["delegation"],
            {
                "role": "summarizer",
                "assigned_by_workflow_id": "wf-parent",
                "assigned_by_run_id": "wf-parent",
                "allowed_capabilities": ["exec"],
                "allowed_tools": ["echo"],
            },
        )
        self.assertEqual(mock_run_agent.call_args.kwargs["shared_memories"], [])
        child_workflow_id = mock_run_agent.call_args.kwargs["run_id"]
        reloaded_parent = workflow.load_workflow("wf-parent")
        self.assertEqual(reloaded_parent.child_workflow_ids, [child_workflow_id])

    def test_start_child_workflow_materializes_shared_memory(self) -> None:
        parent = workflow.create_workflow_state(
            run_id="wf-parent",
            agent="default",
            run_type="model",
            request={"input": "parent", "agent": "default", "tool": None, "tool_args": None},
        )
        workflow.configure_subrun_policy(parent, {"max_children": 1, "max_depth": 1})
        workflow.write_workflow(parent)
        saved_memory = memory.create_memory(
            memory_type="fact",
            scope_kind="workflow",
            workflow_id="wf-parent",
            run_id="wf-parent",
            agent="default",
            payload={"statement": "Parent summary"},
        )

        with patch.object(
            workflow_runner,
            "run_agent",
            return_value={"status": "success", "workflow": {"workflow_id": "wf-child"}},
        ) as mock_run_agent:
            workflow_runner.start_child_workflow(
                "wf-parent",
                user_input="child",
                agent_name="researcher",
                shared_memory_ids=[saved_memory["memory_id"]],
            )

        self.assertEqual(
            mock_run_agent.call_args.kwargs["shared_memories"][0]["memory_id"],
            saved_memory["memory_id"],
        )
        self.assertEqual(
            mock_run_agent.call_args.kwargs["delegation"]["allowed_capabilities"],
            ["model_call"],
        )

    def test_start_child_workflow_rejects_disallowed_agent(self) -> None:
        parent = workflow.create_workflow_state(
            run_id="wf-parent",
            agent="default",
            run_type="model",
            request={"input": "parent", "agent": "default", "tool": None, "tool_args": None},
        )
        workflow.configure_subrun_policy(
            parent,
            {"max_children": 1, "max_depth": 1, "allowed_agents": ["researcher"]},
        )
        workflow.write_workflow(parent)

        with self.assertRaisesRegex(PermissionError, "does not allow agent `default`"):
            workflow_runner.start_child_workflow(
                "wf-parent",
                user_input="child",
                agent_name="default",
            )

    def test_start_child_workflow_rejects_disallowed_shared_memory_scope(self) -> None:
        parent = workflow.create_workflow_state(
            run_id="wf-parent",
            agent="default",
            run_type="model",
            request={"input": "parent", "agent": "default", "tool": None, "tool_args": None},
        )
        workflow.configure_subrun_policy(parent, {"max_children": 1, "max_depth": 1})
        workflow.write_workflow(parent)
        unrelated_memory = memory.create_memory(
            memory_type="fact",
            scope_kind="workflow",
            workflow_id="wf-other",
            run_id="wf-other",
            agent="default",
            payload={"statement": "Unrelated"},
        )

        with self.assertRaisesRegex(PermissionError, "cannot hand off memory"):
            workflow_runner.start_child_workflow(
                "wf-parent",
                user_input="child",
                agent_name="researcher",
                shared_memory_ids=[unrelated_memory["memory_id"]],
            )

    def test_start_child_workflow_registers_failed_child_lineage(self) -> None:
        parent = workflow.create_workflow_state(
            run_id="wf-parent",
            agent="default",
            run_type="model",
            request={"input": "parent", "agent": "default", "tool": None, "tool_args": None},
        )
        workflow.configure_subrun_policy(parent, {"max_children": 2, "max_depth": 1})
        workflow.write_workflow(parent)

        def fail_child(**kwargs):
            child = workflow.create_workflow_state(
                run_id=kwargs["run_id"],
                agent=kwargs["agent_name"],
                run_type="model",
                parent_workflow_id=kwargs["parent_workflow_id"],
                root_workflow_id=kwargs["root_workflow_id"],
                depth=kwargs["workflow_depth"],
                delegation=kwargs["delegation"],
                shared_memories=kwargs["shared_memories"],
            )
            workflow.fail_workflow(child, error_type="RuntimeError", message="child exploded")
            workflow.write_workflow(child)
            raise RuntimeError("child exploded")

        with patch.object(workflow_runner, "run_agent", side_effect=fail_child):
            with self.assertRaisesRegex(RuntimeError, "child exploded"):
                workflow_runner.start_child_workflow(
                    "wf-parent",
                    user_input="child",
                    agent_name="researcher",
                )

        reloaded_parent = workflow.load_workflow("wf-parent")
        self.assertEqual(reloaded_parent.status, "running")
        self.assertEqual(len(reloaded_parent.child_workflow_ids), 1)
        failed_child = workflow.load_workflow(reloaded_parent.child_workflow_ids[0])
        self.assertEqual(failed_child.status, "failed")
        self.assertEqual(failed_child.parent_workflow_id, "wf-parent")

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
