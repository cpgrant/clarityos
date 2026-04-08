import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime.approval as approval
import runtime.artifact as artifact
import runtime.memory as memory
import runtime.queue as queue
import runtime.trace as trace
import runtime.worker as worker
import runtime.workflow as workflow
from runtime.control_plane import (
    queue_health_view,
    recover_workflow,
    worker_health_view,
    workflow_control_view,
    workflow_incident_summary_view,
    workflow_incident_view,
)


class ControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.approval_dir = self.root_dir / "approvals"
        self.artifact_dir = self.root_dir / "artifacts"
        self.memory_dir = self.root_dir / "memories"
        self.job_dir = self.root_dir / "jobs"
        self.log_dir = self.root_dir / "logs"
        self.worker_dir = self.root_dir / "workers"
        self.workflow_dir = self.root_dir / "workflows"
        self.approval_dir.mkdir()
        self.artifact_dir.mkdir()
        self.memory_dir.mkdir()
        self.job_dir.mkdir()
        self.log_dir.mkdir()
        self.worker_dir.mkdir()
        self.workflow_dir.mkdir()
        self.approval_dir_patcher = patch.object(approval, "APPROVAL_DIR", self.approval_dir)
        self.artifact_dir_patcher = patch.object(artifact, "ARTIFACT_DIR", self.artifact_dir)
        self.memory_dir_patcher = patch.object(memory, "MEMORY_DIR", self.memory_dir)
        self.job_dir_patcher = patch.object(queue, "JOB_DIR", self.job_dir)
        self.log_dir_patcher = patch.object(trace, "LOG_DIR", self.log_dir)
        self.worker_dir_patcher = patch.object(worker, "WORKER_DIR", self.worker_dir)
        self.workflow_dir_patcher = patch.object(workflow, "WORKFLOW_DIR", self.workflow_dir)
        self.approval_dir_patcher.start()
        self.artifact_dir_patcher.start()
        self.memory_dir_patcher.start()
        self.job_dir_patcher.start()
        self.log_dir_patcher.start()
        self.worker_dir_patcher.start()
        self.workflow_dir_patcher.start()

    def tearDown(self) -> None:
        self.approval_dir_patcher.stop()
        self.artifact_dir_patcher.stop()
        self.memory_dir_patcher.stop()
        self.job_dir_patcher.stop()
        self.log_dir_patcher.stop()
        self.worker_dir_patcher.stop()
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
        self.assertEqual(view["correlation_ids"]["workflow_ids"], ["wf-parent"])
        self.assertEqual(view["correlation_ids"]["approval_ids"], [approval_record["approval_id"]])
        self.assertEqual(view["correlation_ids"]["artifact_ids"], [saved_artifact["artifact_id"]])
        self.assertEqual(view["correlation_ids"]["memory_ids"], [saved_memory["memory_id"]])
        self.assertEqual(view["correlation_ids"]["shared_memory_ids"], [])
        self.assertEqual(view["correlation_ids"]["child_workflow_ids"], ["wf-child"])
        self.assertEqual(view["correlation_ids"]["trace_ids"], [])
        self.assertEqual(
            view["correlation_ids"]["delegation"],
            {
                "assigned_by_workflow_ids": [],
                "assigned_by_run_ids": [],
            },
        )
        self.assertIn("workflow", view["timelines"])
        self.assertIn("recent", view["timelines"])
        self.assertEqual(view["incident"]["recent_timeline"][0]["source"], "workflow")
        self.assertEqual(view["actions"]["resume"]["available"], True)
        self.assertEqual(view["actions"]["approvals"][0]["approve_path"], f"/approvals/{approval_record['approval_id']}/approve")
        self.assertEqual(view["actions"]["artifacts"][0]["path"], f"/artifacts/{saved_artifact['artifact_id']}")
        self.assertEqual(view["actions"]["memories"][0]["memory_id"], saved_memory["memory_id"])

    def test_workflow_control_view_includes_related_jobs_workers_and_recovery_actions(self) -> None:
        parent = workflow.create_workflow_state(
            run_id="wf-parent",
            agent="default",
            run_type="model",
        )
        workflow.write_workflow(parent)

        failed_job = queue.create_job(
            job_type="workflow_resume",
            payload={"workflow_id": parent.workflow_id, "input": "", "agent": "default", "tool": None, "tool_args": None, "approval_id": None},
            workflow_id=parent.workflow_id,
        )
        queue.update_job(failed_job["job_id"], status="failed", error={"type": "RuntimeError", "message": "boom"})

        registered_worker = worker.register_worker(name="queue-1")
        running_job = queue.create_job(
            job_type="workflow_resume",
            payload={"workflow_id": parent.workflow_id, "input": "", "agent": "default", "tool": None, "tool_args": None, "approval_id": None},
            workflow_id=parent.workflow_id,
        )
        queue.update_job(
            running_job["job_id"],
            status="running",
            worker_id=registered_worker["worker_id"],
            claimed_at="2026-01-01T00:00:00+00:00",
            lease_expires_at="2026-01-01T00:00:00+00:00",
        )
        worker.update_worker(
            registered_worker["worker_id"],
            status="busy",
            current_job_id=running_job["job_id"],
            lease_expires_at="2026-01-01T00:00:00+00:00",
        )

        view = workflow_control_view(parent.workflow_id)

        self.assertEqual(len(view["jobs"]), 2)
        self.assertEqual(len(view["workers"]), 1)
        self.assertEqual(view["recovery"]["failed_job_ids"], [failed_job["job_id"]])
        self.assertEqual(view["recovery"]["expired_running_job_ids"], [running_job["job_id"]])
        self.assertTrue(view["actions"]["recover"]["available"])
        self.assertEqual(view["actions"]["recover"]["path"], f"/workflows/{parent.workflow_id}/recover")
        self.assertFalse(view["actions"]["resume_safe"]["available"])
        self.assertFalse(view["actions"]["replay"]["available"])

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

    def test_workflow_control_view_exposes_safe_resume_and_replay_actions(self) -> None:
        waiting = workflow.create_workflow_state(
            run_id="wf-waiting",
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
            workflow_id=waiting.workflow_id,
            agent="default",
            policy_name="approval_exec",
            action={"capability": "exec", "tool": "echo", "command": "echo", "path": None},
            reason="needs approval",
            request=waiting.request,
        )
        workflow.wait_for_approval(waiting, approval_id=approval_record["approval_id"])
        workflow.write_workflow(waiting)

        failed = workflow.create_workflow_state(
            run_id="wf-failed",
            agent="default",
            run_type="model",
            request={"input": "retry me", "agent": "default", "tool": None, "tool_args": None},
        )
        workflow.fail_workflow(failed, error_type="RuntimeError", message="boom")
        workflow.write_workflow(failed)

        waiting_view = workflow_control_view(waiting.workflow_id)
        failed_view = workflow_control_view(failed.workflow_id)

        self.assertTrue(waiting_view["actions"]["resume_safe"]["available"])
        self.assertTrue(waiting_view["recovery"]["can_safe_resume"])
        self.assertFalse(waiting_view["actions"]["replay"]["available"])
        self.assertTrue(failed_view["actions"]["replay"]["available"])
        self.assertTrue(failed_view["recovery"]["can_replay"])
        self.assertFalse(failed_view["actions"]["resume_safe"]["available"])

    def test_recover_workflow_reclaims_expired_jobs_and_reschedules_failed_jobs(self) -> None:
        parent = workflow.create_workflow_state(
            run_id="wf-parent",
            agent="default",
            run_type="model",
        )
        workflow.write_workflow(parent)

        failed_job = queue.create_job(
            job_type="workflow_resume",
            payload={"workflow_id": parent.workflow_id, "input": "", "agent": "default", "tool": None, "tool_args": None, "approval_id": None},
            workflow_id=parent.workflow_id,
        )
        queue.update_job(failed_job["job_id"], status="failed", error={"type": "RuntimeError", "message": "boom"})

        dead_job = queue.create_job(
            job_type="workflow_resume",
            payload={"workflow_id": parent.workflow_id, "input": "", "agent": "default", "tool": None, "tool_args": None, "approval_id": None},
            workflow_id=parent.workflow_id,
        )
        queue.update_job(dead_job["job_id"], status="dead_letter", dead_lettered_at="2026-01-01T00:00:00+00:00")

        registered_worker = worker.register_worker(name="queue-1")
        running_job = queue.create_job(
            job_type="workflow_resume",
            payload={"workflow_id": parent.workflow_id, "input": "", "agent": "default", "tool": None, "tool_args": None, "approval_id": None},
            workflow_id=parent.workflow_id,
        )
        queue.update_job(
            running_job["job_id"],
            status="running",
            worker_id=registered_worker["worker_id"],
            claimed_at="2026-01-01T00:00:00+00:00",
            lease_expires_at="2026-01-01T00:00:00+00:00",
        )
        worker.update_worker(
            registered_worker["worker_id"],
            status="busy",
            current_job_id=running_job["job_id"],
            lease_expires_at="2026-01-01T00:00:00+00:00",
        )

        recovered = recover_workflow(
            parent.workflow_id,
            reclaim_expired_jobs=True,
            reschedule_failed_jobs=True,
            reschedule_dead_letter_jobs=True,
        )

        self.assertEqual(recovered["reclaimed_job_ids"], [running_job["job_id"]])
        self.assertEqual(set(recovered["rescheduled_job_ids"]), {failed_job["job_id"], dead_job["job_id"]})
        self.assertEqual(queue.load_job(running_job["job_id"])["status"], "queued")
        self.assertEqual(queue.load_job(failed_job["job_id"])["status"], "queued")
        self.assertEqual(queue.load_job(dead_job["job_id"])["status"], "queued")
        self.assertEqual(worker.load_worker(registered_worker["worker_id"])["status"], "idle")

    def test_workflow_incident_view_correlates_related_traces(self) -> None:
        parent = workflow.create_workflow_state(
            run_id="wf-parent",
            agent="default",
            run_type="model",
            request={"input": "hello", "agent": "default", "tool": None, "tool_args": None},
        )
        workflow.configure_subrun_policy(parent, {"max_children": 2, "max_depth": 2})
        workflow.fail_workflow(parent, error_type="RuntimeError", message="boom")
        child = workflow.create_workflow_state(
            run_id="wf-child",
            agent="researcher",
            run_type="model",
            parent_workflow_id=parent.workflow_id,
            root_workflow_id=parent.workflow_id,
            depth=1,
            delegation={
                "role": "researcher",
                "assigned_by_workflow_id": parent.workflow_id,
                "assigned_by_run_id": parent.latest_run_id,
                "allowed_capabilities": ["model_call"],
                "allowed_tools": [],
            },
        )
        workflow.write_workflow(child)
        workflow.register_child_workflow(parent, child_workflow_id=child.workflow_id)
        workflow.write_workflow(parent)

        job = queue.create_job(
            job_type="workflow_resume",
            payload={"workflow_id": parent.workflow_id, "input": "", "agent": "default"},
            workflow_id=parent.workflow_id,
        )
        queue.update_job(job["job_id"], status="failed", error={"type": "RuntimeError", "message": "boom"})

        registered_worker = worker.register_worker(name="queue-1")
        queue.update_job(
            job["job_id"],
            worker_id=registered_worker["worker_id"],
        )

        trace.trace_run(
            {
                "run_id": "wf-child",
                "parent_run_id": parent.latest_run_id,
                "status": "error",
                "agent": "researcher",
                "workflow": {
                    "workflow_id": child.workflow_id,
                    "latest_run_id": child.latest_run_id,
                    "status": child.status,
                },
                "correlation_ids": {
                    "run_ids": ["wf-child", parent.latest_run_id],
                    "workflow_ids": [child.workflow_id, parent.workflow_id],
                    "job_ids": [job["job_id"]],
                    "worker_ids": [registered_worker["worker_id"]],
                    "approval_ids": [],
                    "artifact_ids": [],
                    "memory_ids": [],
                    "shared_memory_ids": [],
                    "child_workflow_ids": [child.workflow_id],
                    "delegation": {
                        "assigned_by_workflow_id": parent.workflow_id,
                        "assigned_by_run_id": parent.latest_run_id,
                    },
                },
                "result": {
                    "error": {
                        "error_type": "RuntimeError",
                        "message": "boom",
                    }
                },
            }
        )
        trace.trace_run(
            {
                "run_id": "unrelated-run",
                "parent_run_id": None,
                "status": "success",
                "agent": "default",
                "workflow": {
                    "workflow_id": "wf-other",
                    "latest_run_id": "wf-other",
                    "status": "succeeded",
                },
                "result": {},
            }
        )

        incident = workflow_incident_view(parent.workflow_id)

        self.assertEqual(incident["workflow_id"], "wf-parent")
        self.assertEqual(incident["incident"]["trace_count"], 1)
        self.assertEqual(incident["incident"]["status_counts"]["error"], 1)
        self.assertEqual(incident["incident"]["classifications"]["counts"]["runtime_error"], 2)
        self.assertIn("job_failed", incident["incident"]["classifications"]["counts"])
        self.assertEqual(incident["incident"]["recent_events"][0]["source"], "trace")
        self.assertEqual(incident["traces"][0]["workflow_id"], "wf-child")
        self.assertEqual(incident["jobs"][0]["job_id"], job["job_id"])
        self.assertEqual(incident["workers"][0]["worker_id"], registered_worker["worker_id"])
        self.assertEqual(incident["correlation_ids"]["workflow_ids"], ["wf-parent", "wf-child"])
        self.assertEqual(incident["correlation_ids"]["run_ids"], ["wf-parent", "wf-child"])
        self.assertEqual(incident["correlation_ids"]["job_ids"], [job["job_id"]])
        self.assertEqual(incident["correlation_ids"]["worker_ids"], [registered_worker["worker_id"]])
        self.assertEqual(incident["correlation_ids"]["child_workflow_ids"], ["wf-child"])
        self.assertEqual(
            incident["correlation_ids"]["delegation"],
            {
                "assigned_by_workflow_ids": [parent.workflow_id],
                "assigned_by_run_ids": [parent.latest_run_id],
            },
        )
        self.assertEqual(len(incident["correlation_ids"]["trace_ids"]), 1)
        self.assertIn("recent", incident["timelines"])
        self.assertIn("traces", incident["timelines"])
        self.assertIn("causality_chain", incident["timelines"])
        recent_sources = {entry["source"] for entry in incident["timelines"]["recent"]}
        self.assertIn("workflow", recent_sources)
        self.assertIn("job", recent_sources)
        self.assertIn("worker", recent_sources)
        self.assertEqual(incident["incident"]["recent_timeline"][0]["source"], incident["timelines"]["recent"][0]["source"])
        self.assertEqual(incident["incident"]["causality_chain"][0]["source"], "trace")
        self.assertEqual(incident["incident"]["rollup"]["first_failure"]["source"], "workflow")
        self.assertEqual(incident["incident"]["rollup"]["latest_failure"]["source"], "trace")
        self.assertEqual(incident["incident"]["rollup"]["current_blocker"]["kind"], "runtime_error")

    def test_workflow_incident_summary_view_exposes_compact_rollup(self) -> None:
        state = workflow.create_workflow_state(
            run_id="wf-summary",
            agent="default",
            run_type="model",
            request={"input": "hello", "agent": "default", "tool": None, "tool_args": None},
        )
        workflow.fail_workflow(state, error_type="RuntimeError", message="boom")
        workflow.write_workflow(state)

        failed_job = queue.create_job(
            job_type="workflow_resume",
            payload={"workflow_id": state.workflow_id, "input": "", "agent": "default"},
            workflow_id=state.workflow_id,
        )
        queue.update_job(failed_job["job_id"], status="failed", error={"type": "RuntimeError", "message": "boom"})

        trace.trace_run(
            {
                "run_id": state.latest_run_id,
                "status": "error",
                "agent": "default",
                "workflow": {
                    "workflow_id": state.workflow_id,
                    "latest_run_id": state.latest_run_id,
                    "status": state.status,
                },
                "correlation_ids": {
                    "run_ids": [state.latest_run_id],
                    "workflow_ids": [state.workflow_id],
                    "job_ids": [failed_job["job_id"]],
                    "worker_ids": [],
                    "approval_ids": [],
                    "artifact_ids": [],
                    "memory_ids": [],
                    "shared_memory_ids": [],
                    "child_workflow_ids": [],
                    "delegation": {
                        "assigned_by_workflow_id": None,
                        "assigned_by_run_id": None,
                    },
                },
                "result": {
                    "error": {
                        "error_type": "RuntimeError",
                        "message": "boom",
                    }
                },
            }
        )

        summary = workflow_incident_summary_view(state.workflow_id)

        self.assertEqual(summary["workflow_id"], state.workflow_id)
        self.assertEqual(summary["workflow_status"], "failed")
        self.assertEqual(summary["incident"]["rollup"]["current_blocker"]["kind"], "runtime_error")
        self.assertEqual(summary["incident"]["rollup"]["latest_failure"]["source"], "trace")
        self.assertEqual(summary["queue_health"]["health"]["failed_count"], 1)
        self.assertIn("recent_events", summary["worker_health"]["trends"])

    def test_queue_and_worker_health_views_surface_runtime_health(self) -> None:
        job = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
        )
        queue.update_job(
            job["job_id"],
            status="running",
            worker_id="worker-123",
            claimed_at="2026-01-01T00:00:00+00:00",
            lease_expires_at="2026-01-01T00:00:00+00:00",
        )
        registered_worker = worker.register_worker(name="queue-1")
        worker.update_worker(
            registered_worker["worker_id"],
            status="busy",
            current_job_id="missing-job",
            lease_expires_at="2026-01-01T00:00:00+00:00",
        )

        queue_health = queue_health_view()
        workers_health = worker_health_view()

        self.assertEqual(queue_health["health"]["expired_running_count"], 1)
        self.assertIn("recent_events", queue_health["health"]["trends"])
        self.assertIn(registered_worker["worker_id"], workers_health["orphaned_worker_ids"])
        self.assertIn(registered_worker["worker_id"], workers_health["expired_worker_ids"])
        self.assertIn("recent_events", workers_health["trends"])


if __name__ == "__main__":
    unittest.main()
