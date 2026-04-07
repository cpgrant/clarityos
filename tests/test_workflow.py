import tempfile
import unittest
from pathlib import Path

from runtime.workflow import (
    can_retry,
    can_spawn_child_workflow,
    configure_retry_policy,
    configure_subrun_policy,
    attach_run_to_workflow,
    complete_finish_step,
    complete_workflow,
    create_workflow_state,
    fail_workflow,
    load_workflow,
    mark_action_completed,
    register_child_workflow,
    register_artifact,
    register_memory,
    resume_from_retry,
    resume_from_approval,
    set_action_details,
    wait_for_retry,
    wait_for_approval,
    write_workflow,
    workflow_snapshot,
)
from unittest.mock import patch


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.workflow_dir = self.root_dir / "workflows"
        self.workflow_dir.mkdir()
        self.workflow_dir_patcher = patch("runtime.workflow.WORKFLOW_DIR", self.workflow_dir)
        self.workflow_dir_patcher.start()

    def tearDown(self) -> None:
        self.workflow_dir_patcher.stop()
        self.temp_dir.cleanup()

    def test_create_workflow_state_for_model_run(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="model",
        )

        snapshot = workflow_snapshot(workflow)

        self.assertEqual(snapshot["workflow_id"], "run-123")
        self.assertEqual(snapshot["root_workflow_id"], "run-123")
        self.assertIsNone(snapshot["parent_workflow_id"])
        self.assertEqual(snapshot["depth"], 0)
        self.assertEqual(snapshot["child_workflow_ids"], [])
        self.assertEqual(snapshot["status"], "running")
        self.assertEqual(snapshot["current_step_id"], "model_step")
        self.assertEqual(snapshot["request"], {})
        self.assertEqual(snapshot["steps"][0]["step_type"], "model")
        self.assertEqual(snapshot["steps"][0]["status"], "in_progress")
        self.assertEqual(snapshot["steps"][1]["step_type"], "finish")
        self.assertEqual(snapshot["steps"][1]["status"], "pending")

    def test_write_and_load_workflow_round_trip(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="model",
        )
        attach_run_to_workflow(workflow, run_id="run-456")

        snapshot = write_workflow(workflow)
        loaded = load_workflow(workflow.workflow_id)

        self.assertEqual(snapshot["workflow_id"], "run-123")
        self.assertEqual(loaded.workflow_id, "run-123")
        self.assertEqual(loaded.latest_run_id, "run-456")
        self.assertEqual(loaded.status, "running")
        self.assertEqual(loaded.retry_policy["max_attempts"], 0)

    def test_register_child_workflow_tracks_lineage(self) -> None:
        parent = create_workflow_state(
            run_id="parent-123",
            agent="default",
            run_type="model",
        )
        configure_subrun_policy(parent, {"max_children": 1, "max_depth": 1})

        child = create_workflow_state(
            run_id="child-123",
            agent="researcher",
            run_type="tool",
            parent_workflow_id=parent.workflow_id,
            root_workflow_id=parent.root_workflow_id,
            depth=parent.depth + 1,
        )
        register_child_workflow(parent, child_workflow_id=child.workflow_id)

        parent_snapshot = workflow_snapshot(parent)
        child_snapshot = workflow_snapshot(child)

        self.assertEqual(parent_snapshot["child_workflow_ids"], ["child-123"])
        self.assertFalse(can_spawn_child_workflow(parent))
        self.assertEqual(child_snapshot["parent_workflow_id"], "parent-123")
        self.assertEqual(child_snapshot["root_workflow_id"], "parent-123")
        self.assertEqual(child_snapshot["depth"], 1)

    def test_write_and_load_workflow_persists_request(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="tool",
            request={
                "input": "",
                "agent": "default",
                "tool": "echo",
                "tool_args": {"text": "hello"},
            },
        )

        write_workflow(workflow)
        loaded = load_workflow(workflow.workflow_id)

        self.assertEqual(
            loaded.request,
            {
                "input": "",
                "agent": "default",
                "tool": "echo",
                "tool_args": {"text": "hello"},
            },
        )

    def test_write_and_load_workflow_persists_artifacts(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="model",
        )
        register_artifact(
            workflow,
            {
                "artifact_id": "artifact-123",
                "workflow_id": "run-123",
                "run_id": "run-123",
                "name": "result",
                "kind": "model_output",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "metadata": {"model": "fake-model"},
            },
        )

        write_workflow(workflow)
        loaded = load_workflow(workflow.workflow_id)

        self.assertEqual(len(loaded.artifacts), 1)
        self.assertEqual(loaded.artifacts[0]["artifact_id"], "artifact-123")

    def test_write_and_load_workflow_persists_memories(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="tool",
        )
        register_memory(
            workflow,
            {
                "memory_id": "memory-123",
                "memory_type": "fact",
                "scope": {"kind": "workflow", "value": "run-123"},
                "agent": "default",
                "workflow_id": "run-123",
                "run_id": "run-123",
                "tags": ["runtime"],
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "metadata": {},
                "payload_summary": "Retries are bounded",
            },
        )

        write_workflow(workflow)
        loaded = load_workflow(workflow.workflow_id)

        self.assertEqual(len(loaded.memories), 1)
        self.assertEqual(loaded.memories[0]["memory_id"], "memory-123")

    def test_wait_for_approval_blocks_action_and_adds_step(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="tool",
        )
        set_action_details(workflow, tool="echo")

        wait_for_approval(
            workflow,
            approval_id="approval-123",
            details={"reason": "needs approval"},
        )

        snapshot = workflow_snapshot(workflow)

        self.assertEqual(snapshot["status"], "waiting")
        self.assertEqual(snapshot["current_step_id"], "approval_wait:approval-123")
        self.assertEqual(snapshot["steps"][0]["status"], "blocked")
        self.assertEqual(snapshot["steps"][1]["step_type"], "approval_wait")
        self.assertEqual(snapshot["steps"][1]["status"], "in_progress")
        self.assertEqual(snapshot["steps"][1]["details"]["approval_id"], "approval-123")

    def test_resume_from_approval_returns_to_action_step(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="tool",
        )
        wait_for_approval(workflow, approval_id="approval-123")

        resume_from_approval(workflow, approval_id="approval-123")

        snapshot = workflow_snapshot(workflow)

        self.assertEqual(snapshot["status"], "running")
        self.assertEqual(snapshot["current_step_id"], "tool_step")
        self.assertEqual(snapshot["steps"][0]["status"], "in_progress")
        self.assertEqual(snapshot["steps"][1]["status"], "completed")

    def test_wait_for_retry_blocks_action_and_adds_retry_step(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="tool",
        )
        configure_retry_policy(workflow, {"max_attempts": 1, "backoff_seconds": 0})

        wait_for_retry(
            workflow,
            error_type="TimeoutError",
            message="transient timeout",
            retryable=True,
        )

        snapshot = workflow_snapshot(workflow)

        self.assertEqual(snapshot["status"], "waiting")
        self.assertEqual(snapshot["current_step_id"], "retry_wait:1")
        self.assertEqual(snapshot["steps"][0]["status"], "blocked")
        self.assertEqual(snapshot["steps"][1]["step_type"], "retry_wait")
        self.assertEqual(snapshot["retry_state"]["attempts_used"], 1)
        self.assertEqual(snapshot["retry_state"]["retries_remaining"], 0)
        self.assertFalse(can_retry(workflow))

    def test_resume_from_retry_returns_to_action_step(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="tool",
        )
        configure_retry_policy(workflow, {"max_attempts": 1, "backoff_seconds": 0})
        wait_for_retry(
            workflow,
            error_type="TimeoutError",
            message="transient timeout",
            retryable=True,
        )

        resume_from_retry(workflow)

        snapshot = workflow_snapshot(workflow)

        self.assertEqual(snapshot["status"], "running")
        self.assertEqual(snapshot["current_step_id"], "tool_step")
        self.assertIsNone(snapshot["retry_state"]["next_retry_at"])
        self.assertEqual(snapshot["steps"][0]["status"], "in_progress")
        self.assertEqual(snapshot["steps"][1]["status"], "completed")

    def test_complete_workflow_marks_finish_step(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="model",
        )

        complete_workflow(workflow)

        snapshot = workflow_snapshot(workflow)

        self.assertEqual(snapshot["status"], "succeeded")
        self.assertEqual(snapshot["current_step_id"], "finish_step")
        self.assertEqual(snapshot["steps"][0]["status"], "completed")
        self.assertEqual(snapshot["steps"][1]["status"], "completed")

    def test_mark_action_completed_advances_to_finish_step(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="tool",
        )

        mark_action_completed(workflow)

        snapshot = workflow_snapshot(workflow)

        self.assertEqual(snapshot["status"], "running")
        self.assertEqual(snapshot["current_step_id"], "finish_step")
        self.assertEqual(snapshot["steps"][0]["status"], "completed")
        self.assertEqual(snapshot["steps"][1]["status"], "in_progress")

    def test_complete_finish_step_marks_workflow_succeeded(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="tool",
        )
        mark_action_completed(workflow)

        complete_finish_step(workflow)

        snapshot = workflow_snapshot(workflow)

        self.assertEqual(snapshot["status"], "succeeded")
        self.assertEqual(snapshot["current_step_id"], "finish_step")
        self.assertEqual(snapshot["steps"][1]["status"], "completed")

    def test_fail_workflow_marks_current_step_failed(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="tool",
        )

        fail_workflow(
            workflow,
            error_type="RuntimeError",
            message="boom",
        )

        snapshot = workflow_snapshot(workflow)

        self.assertEqual(snapshot["status"], "failed")
        self.assertEqual(snapshot["steps"][0]["status"], "failed")
        self.assertEqual(snapshot["steps"][0]["error"]["error_type"], "RuntimeError")
        self.assertEqual(snapshot["steps"][0]["error"]["message"], "boom")

    def test_load_missing_workflow_raises_not_found(self) -> None:
        with self.assertRaisesRegex(FileNotFoundError, "Workflow not found: missing"):
            load_workflow("missing")


if __name__ == "__main__":
    unittest.main()
