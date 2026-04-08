import json
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
        self.assertEqual(snapshot["shared_memories"], [])
        self.assertEqual(snapshot["delegation"], {})
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

    def test_write_workflow_tracks_transition_history(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="tool",
        )
        write_workflow(workflow)

        configure_retry_policy(workflow, {"max_attempts": 1, "backoff_seconds": 0})
        wait_for_retry(
            workflow,
            error_type="TimeoutError",
            message="transient timeout",
            retryable=True,
        )
        write_workflow(workflow)

        loaded = load_workflow("run-123")
        event_types = [entry["event_type"] for entry in loaded.transition_history]

        self.assertIn("created", event_types)
        self.assertIn("workflow_status_changed", event_types)
        self.assertIn("current_step_changed", event_types)
        self.assertIn("step_status_changed", event_types)
        self.assertIn("retry_state_updated", event_types)

    def test_write_workflow_persists_versioned_state_envelope(self) -> None:
        workflow = create_workflow_state(
            run_id="run-123",
            agent="default",
            run_type="model",
        )

        snapshot = write_workflow(workflow)

        with (self.workflow_dir / "run-123.json").open(encoding="utf-8") as file:
            saved = json.load(file)

        self.assertEqual(saved["schema"], "workflow.v1")
        self.assertEqual(saved["version"], "v0.9")
        self.assertEqual(saved["payload"]["workflow_id"], snapshot["workflow_id"])

    def test_load_workflow_accepts_legacy_unversioned_snapshot(self) -> None:
        legacy_snapshot = {
            "workflow_id": "legacy-123",
            "run_id": "legacy-123",
            "latest_run_id": "legacy-123",
            "root_workflow_id": "legacy-123",
            "parent_workflow_id": None,
            "depth": 0,
            "child_workflow_ids": [],
            "agent": "default",
            "run_type": "model",
            "request": {},
            "artifacts": [],
            "memories": [],
            "shared_memories": [],
            "subrun_policy": {
                "max_children": 0,
                "max_depth": 0,
                "allowed_agents": None,
                "allowed_capabilities": None,
                "allowed_tools": None,
            },
            "delegation": {},
            "retry_policy": {"max_attempts": 0, "backoff_seconds": 0},
            "retry_state": {
                "attempts_used": 0,
                "retries_remaining": 0,
                "next_retry_at": None,
                "last_error": None,
            },
            "status": "running",
            "current_step_id": "model_step",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "steps": [
                {
                    "step_id": "model_step",
                    "step_type": "model",
                    "status": "in_progress",
                    "details": {},
                    "error": None,
                },
                {
                    "step_id": "finish_step",
                    "step_type": "finish",
                    "status": "pending",
                    "details": {},
                    "error": None,
                },
            ],
        }

        with (self.workflow_dir / "legacy-123.json").open("w", encoding="utf-8") as file:
            json.dump(legacy_snapshot, file, indent=2)

        loaded = load_workflow("legacy-123")

        self.assertEqual(loaded.workflow_id, "legacy-123")
        self.assertEqual(loaded.status, "running")

    def test_write_workflow_rewrites_legacy_snapshot_as_versioned_state(self) -> None:
        legacy_snapshot = {
            "workflow_id": "legacy-123",
            "run_id": "legacy-123",
            "latest_run_id": "legacy-123",
            "root_workflow_id": "legacy-123",
            "parent_workflow_id": None,
            "depth": 0,
            "child_workflow_ids": [],
            "agent": "default",
            "run_type": "model",
            "request": {},
            "artifacts": [],
            "memories": [],
            "shared_memories": [],
            "subrun_policy": {"max_children": 0, "max_depth": 0, "allowed_agents": None, "allowed_capabilities": None, "allowed_tools": None},
            "delegation": {},
            "retry_policy": {"max_attempts": 0, "backoff_seconds": 0},
            "retry_state": {"attempts_used": 0, "retries_remaining": 0, "next_retry_at": None, "last_error": None},
            "status": "running",
            "current_step_id": "model_step",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "steps": [
                {"step_id": "model_step", "step_type": "model", "status": "in_progress", "details": {}, "error": None},
                {"step_id": "finish_step", "step_type": "finish", "status": "pending", "details": {}, "error": None},
            ],
        }

        path = self.workflow_dir / "legacy-123.json"
        with path.open("w", encoding="utf-8") as file:
            json.dump(legacy_snapshot, file, indent=2)

        loaded = load_workflow("legacy-123")
        write_workflow(loaded)

        with path.open(encoding="utf-8") as file:
            saved = json.load(file)

        self.assertEqual(saved["schema"], "workflow.v1")
        self.assertEqual(saved["version"], "v0.9")

    def test_load_workflow_backfills_missing_legacy_fields(self) -> None:
        legacy_snapshot = {
            "workflow_id": "legacy-minimal",
            "run_id": "legacy-minimal",
            "agent": "default",
            "run_type": "model",
            "status": "running",
            "current_step_id": "model_step",
            "steps": [
                {"step_id": "model_step", "step_type": "model", "status": "in_progress"},
                {"step_id": "finish_step", "step_type": "finish", "status": "pending"},
            ],
        }

        with (self.workflow_dir / "legacy-minimal.json").open("w", encoding="utf-8") as file:
            json.dump(legacy_snapshot, file, indent=2)

        loaded = load_workflow("legacy-minimal")

        self.assertEqual(loaded.latest_run_id, "legacy-minimal")
        self.assertEqual(loaded.root_workflow_id, "legacy-minimal")
        self.assertEqual(loaded.depth, 0)
        self.assertEqual(loaded.shared_memories, [])
        self.assertEqual(loaded.retry_policy["max_attempts"], 0)
        self.assertEqual(loaded.retry_state["retries_remaining"], 0)

    def test_load_workflow_rejects_schema_mismatch(self) -> None:
        with (self.workflow_dir / "bad-schema.json").open("w", encoding="utf-8") as file:
            json.dump(
                {
                    "schema": "job.v1",
                    "version": "v0.9",
                    "payload": {"workflow_id": "bad-schema"},
                },
                file,
                indent=2,
            )

        with self.assertRaisesRegex(
            ValueError,
            "Persisted state schema mismatch: expected `workflow.v1`, got `job.v1`",
        ):
            load_workflow("bad-schema")

    def test_load_workflow_rejects_future_version(self) -> None:
        with (self.workflow_dir / "future-version.json").open("w", encoding="utf-8") as file:
            json.dump(
                {
                    "schema": "workflow.v1",
                    "version": "v9.9",
                    "payload": {"workflow_id": "future-version"},
                },
                file,
                indent=2,
            )

        with self.assertRaisesRegex(
            ValueError,
            "Persisted state version `v9.9` is newer than supported version `v0.9`",
        ):
            load_workflow("future-version")

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

    def test_create_workflow_state_persists_delegation_and_shared_memory(self) -> None:
        workflow = create_workflow_state(
            run_id="child-123",
            agent="researcher",
            run_type="model",
            parent_workflow_id="parent-123",
            root_workflow_id="parent-123",
            depth=1,
            delegation={
                "role": "summarizer",
                "assigned_by_workflow_id": "parent-123",
                "assigned_by_run_id": "run-parent",
                "allowed_capabilities": ["model_call"],
                "allowed_tools": [],
            },
            shared_memories=[
                {
                    "memory_id": "memory-123",
                    "memory_type": "fact",
                    "scope": {"kind": "workflow", "value": "parent-123"},
                    "workflow_id": "parent-123",
                    "payload_summary": "Parent result summary",
                }
            ],
        )

        snapshot = workflow_snapshot(workflow)

        self.assertEqual(snapshot["delegation"]["role"], "summarizer")
        self.assertEqual(snapshot["delegation"]["allowed_capabilities"], ["model_call"])
        self.assertEqual(snapshot["shared_memories"][0]["memory_id"], "memory-123")

    def test_write_and_load_workflow_persists_delegation_and_shared_memory(self) -> None:
        workflow = create_workflow_state(
            run_id="child-123",
            agent="researcher",
            run_type="model",
            parent_workflow_id="parent-123",
            root_workflow_id="parent-123",
            depth=1,
            delegation={
                "role": "summarizer",
                "assigned_by_workflow_id": "parent-123",
                "assigned_by_run_id": "run-parent",
                "allowed_capabilities": ["model_call"],
                "allowed_tools": [],
            },
            shared_memories=[
                {
                    "memory_id": "memory-123",
                    "memory_type": "fact",
                    "scope": {"kind": "workflow", "value": "parent-123"},
                    "workflow_id": "parent-123",
                    "payload_summary": "Parent result summary",
                }
            ],
        )

        write_workflow(workflow)
        loaded = load_workflow(workflow.workflow_id)

        self.assertEqual(loaded.delegation["role"], "summarizer")
        self.assertEqual(loaded.delegation["allowed_capabilities"], ["model_call"])
        self.assertEqual(loaded.shared_memories[0]["memory_id"], "memory-123")

    def test_configure_subrun_policy_accepts_delegation_bounds(self) -> None:
        workflow = create_workflow_state(
            run_id="parent-123",
            agent="default",
            run_type="model",
        )

        configure_subrun_policy(
            workflow,
            {
                "max_children": 2,
                "max_depth": 2,
                "allowed_agents": ["researcher"],
                "allowed_capabilities": ["model_call", "memory_read"],
                "allowed_tools": ["read_file"],
            },
        )

        snapshot = workflow_snapshot(workflow)

        self.assertEqual(snapshot["subrun_policy"]["allowed_agents"], ["researcher"])
        self.assertEqual(snapshot["subrun_policy"]["allowed_capabilities"], ["model_call", "memory_read"])
        self.assertEqual(snapshot["subrun_policy"]["allowed_tools"], ["read_file"])

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
