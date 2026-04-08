import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import runtime.approval as approval
import runtime.artifact as artifact
import runtime.control_plane as control_plane
import runtime.memory as memory
import runtime.queue as queue
import runtime.trace as trace
import runtime.worker as worker
import runtime.workflow as workflow
import runtime.workflow_runner as workflow_runner


class ResilienceTests(unittest.TestCase):
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
        self.patchers = [
            patch.object(approval, "APPROVAL_DIR", self.approval_dir),
            patch.object(artifact, "ARTIFACT_DIR", self.artifact_dir),
            patch.object(memory, "MEMORY_DIR", self.memory_dir),
            patch.object(queue, "JOB_DIR", self.job_dir),
            patch.object(trace, "LOG_DIR", self.log_dir),
            patch.object(worker, "WORKER_DIR", self.worker_dir),
            patch.object(workflow, "WORKFLOW_DIR", self.workflow_dir),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def test_workflow_incident_summary_survives_persisted_reload(self) -> None:
        state = workflow.create_workflow_state(
            run_id="wf-resilience",
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
        queue.update_job(
            failed_job["job_id"],
            status="failed",
            error={"type": "RuntimeError", "message": "boom"},
        )
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

        summary = control_plane.workflow_incident_summary_view("wf-resilience")

        self.assertEqual(summary["workflow_status"], "failed")
        self.assertEqual(summary["incident"]["rollup"]["first_failure"]["source"], "workflow")
        self.assertEqual(summary["incident"]["rollup"]["latest_failure"]["source"], "trace")
        self.assertEqual(summary["queue_health"]["health"]["failed_count"], 1)

    def test_recover_workflow_repairs_persisted_partial_failure_state(self) -> None:
        state = workflow.create_workflow_state(
            run_id="wf-recover",
            agent="default",
            run_type="model",
        )
        workflow.write_workflow(state)

        failed_job = queue.create_job(
            job_type="workflow_resume",
            payload={"workflow_id": state.workflow_id, "input": "", "agent": "default"},
            workflow_id=state.workflow_id,
        )
        queue.update_job(failed_job["job_id"], status="failed", error={"type": "RuntimeError", "message": "boom"})

        registered_worker = worker.register_worker(name="queue-1")
        running_job = queue.create_job(
            job_type="workflow_resume",
            payload={"workflow_id": state.workflow_id, "input": "", "agent": "default"},
            workflow_id=state.workflow_id,
        )
        expired_at = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        queue.update_job(
            running_job["job_id"],
            status="running",
            worker_id=registered_worker["worker_id"],
            claimed_at=expired_at,
            lease_expires_at=expired_at,
        )
        worker.update_worker(
            registered_worker["worker_id"],
            status="busy",
            current_job_id=running_job["job_id"],
            lease_expires_at=expired_at,
        )

        recovered = control_plane.recover_workflow(
            state.workflow_id,
            reclaim_expired_jobs=True,
            reschedule_failed_jobs=True,
        )

        self.assertEqual(recovered["reclaimed_count"], 1)
        self.assertEqual(recovered["rescheduled_count"], 1)
        self.assertEqual(queue.load_job(running_job["job_id"])["status"], "queued")
        self.assertEqual(queue.load_job(failed_job["job_id"])["status"], "queued")
        self.assertEqual(worker.load_worker(registered_worker["worker_id"])["status"], "idle")

    def test_safe_resume_workflow_after_persisted_retry_wait(self) -> None:
        state = workflow.create_workflow_state(
            run_id="wf-retry",
            agent="default",
            run_type="model",
            request={"input": "retry me", "agent": "default", "tool": None, "tool_args": None},
        )
        workflow.configure_retry_policy(state, {"max_attempts": 1, "backoff_seconds": 0})
        workflow.wait_for_retry(
            state,
            error_type="RuntimeError",
            message="temporary failure",
            retryable=True,
        )
        workflow.write_workflow(state)

        with patch.object(workflow_runner, "run_agent", return_value={"status": "success"}) as mock_run_agent:
            resumed = workflow_runner.safe_resume_workflow(state.workflow_id)

        self.assertEqual(resumed["status"], "success")
        mock_run_agent.assert_called_once_with(
            user_input="retry me",
            agent_name="default",
            tool_name=None,
            tool_args=None,
            approval_id=None,
            job_id=None,
            worker_id=None,
        )


if __name__ == "__main__":
    unittest.main()
