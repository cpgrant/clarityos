import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import runtime.queue as queue
import runtime.worker as worker


class WorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.job_dir = self.root_dir / "jobs"
        self.worker_dir = self.root_dir / "workers"
        self.job_dir.mkdir()
        self.worker_dir.mkdir()
        self.job_dir_patcher = patch.object(queue, "JOB_DIR", self.job_dir)
        self.worker_dir_patcher = patch.object(worker, "WORKER_DIR", self.worker_dir)
        self.job_dir_patcher.start()
        self.worker_dir_patcher.start()

    def tearDown(self) -> None:
        self.job_dir_patcher.stop()
        self.worker_dir_patcher.stop()
        self.temp_dir.cleanup()

    def test_register_worker_creates_idle_worker(self) -> None:
        created = worker.register_worker(name="queue-1", lease_seconds=45)

        self.assertEqual(created["name"], "queue-1")
        self.assertEqual(created["status"], "idle")
        self.assertEqual(created["lease_seconds"], 45)
        loaded = worker.load_worker(created["worker_id"])
        self.assertEqual(loaded["worker_id"], created["worker_id"])

    def test_claim_next_job_assigns_highest_priority_ready_job(self) -> None:
        low = queue.create_job(
            job_type="workflow_start",
            payload={"input": "low", "agent": "default"},
            priority=10,
        )
        high = queue.create_job(
            job_type="workflow_start",
            payload={"input": "high", "agent": "default"},
            priority=100,
        )
        registered_worker = worker.register_worker()

        claimed = worker.claim_next_job(registered_worker["worker_id"])

        self.assertEqual(claimed["job_id"], high["job_id"])
        self.assertEqual(claimed["status"], "running")
        self.assertEqual(claimed["worker_id"], registered_worker["worker_id"])
        self.assertEqual(queue.load_job(low["job_id"])["status"], "queued")
        self.assertEqual(worker.load_worker(registered_worker["worker_id"])["current_job_id"], high["job_id"])

    def test_claim_next_job_promotes_due_scheduled_job(self) -> None:
        created_job = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
        )
        queue.update_job(
            created_job["job_id"],
            status="scheduled",
            ready_at=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
        )
        registered_worker = worker.register_worker()

        claimed = worker.claim_next_job(registered_worker["worker_id"])

        self.assertEqual(claimed["job_id"], created_job["job_id"])
        self.assertEqual(claimed["status"], "running")
        self.assertEqual(queue.load_job(created_job["job_id"])["status"], "running")

    @patch.object(worker, "start_workflow", return_value={"status": "success", "workflow": {"workflow_id": "wf-123"}})
    def test_run_next_job_executes_and_completes_job(self, _mock_start_workflow) -> None:
        created_job = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
        )
        registered_worker = worker.register_worker()

        completed = worker.run_next_job(registered_worker["worker_id"])

        self.assertEqual(completed["job_id"], created_job["job_id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["status"], "success")
        self.assertEqual(worker.load_worker(registered_worker["worker_id"])["status"], "idle")

    @patch.object(worker, "resume_workflow", side_effect=RuntimeError("resume exploded"))
    def test_run_claimed_job_marks_failure(self, _mock_resume_workflow) -> None:
        created_job = queue.create_job(
            job_type="workflow_resume",
            payload={"workflow_id": "wf-123", "input": "", "agent": "default", "tool": None, "tool_args": None, "approval_id": None},
            workflow_id="wf-123",
            max_attempts=1,
        )
        registered_worker = worker.register_worker()
        claimed = worker.claim_next_job(registered_worker["worker_id"])

        failed = worker.run_claimed_job(registered_worker["worker_id"], claimed["job_id"])

        self.assertEqual(failed["job_id"], created_job["job_id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"]["message"], "resume exploded")
        self.assertEqual(worker.load_worker(registered_worker["worker_id"])["status"], "idle")

    @patch.object(worker, "resume_workflow", side_effect=RuntimeError("resume exploded"))
    def test_run_claimed_job_schedules_retry_when_retry_budget_exists(self, _mock_resume_workflow) -> None:
        created_job = queue.create_job(
            job_type="workflow_resume",
            payload={"workflow_id": "wf-123", "input": "", "agent": "default", "tool": None, "tool_args": None, "approval_id": None},
            workflow_id="wf-123",
            max_attempts=3,
            retry_backoff_seconds=5,
        )
        registered_worker = worker.register_worker()
        claimed = worker.claim_next_job(registered_worker["worker_id"])

        retried = worker.run_claimed_job(registered_worker["worker_id"], claimed["job_id"])

        self.assertEqual(retried["job_id"], created_job["job_id"])
        self.assertEqual(retried["status"], "scheduled")
        self.assertEqual(retried["attempt_count"], 1)
        self.assertEqual(retried["error"]["message"], "resume exploded")
        self.assertIsNotNone(retried["next_retry_at"])
        self.assertEqual(worker.load_worker(registered_worker["worker_id"])["status"], "idle")

    @patch.object(worker, "resume_workflow", side_effect=RuntimeError("resume exploded"))
    def test_run_claimed_job_dead_letters_after_attempts_exhausted(self, _mock_resume_workflow) -> None:
        created_job = queue.create_job(
            job_type="workflow_resume",
            payload={"workflow_id": "wf-123", "input": "", "agent": "default", "tool": None, "tool_args": None, "approval_id": None},
            workflow_id="wf-123",
            max_attempts=2,
            retry_backoff_seconds=0,
        )
        registered_worker = worker.register_worker()

        first = worker.run_next_job(registered_worker["worker_id"])
        self.assertEqual(first["status"], "queued")

        second = worker.run_next_job(registered_worker["worker_id"])

        self.assertEqual(second["job_id"], created_job["job_id"])
        self.assertEqual(second["status"], "dead_letter")
        self.assertEqual(second["attempt_count"], 2)
        self.assertEqual(second["error"]["message"], "resume exploded")

    def test_reclaim_expired_leases_requeues_running_job(self) -> None:
        created_job = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
        )
        registered_worker = worker.register_worker()
        claimed = worker.claim_next_job(registered_worker["worker_id"])

        queue.update_job(
            claimed["job_id"],
            lease_expires_at=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
        )
        worker.update_worker(
            registered_worker["worker_id"],
            lease_expires_at=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
        )

        reclaimed = worker.reclaim_expired_leases()

        self.assertEqual(reclaimed["reclaimed_count"], 1)
        reloaded_job = queue.load_job(created_job["job_id"])
        self.assertEqual(reloaded_job["status"], "queued")
        self.assertEqual(reloaded_job["reclaim_count"], 1)
        self.assertIn("Lease expired", reloaded_job["last_requeue_reason"])
        reloaded_worker = worker.load_worker(registered_worker["worker_id"])
        self.assertEqual(reloaded_worker["status"], "idle")
        self.assertIsNone(reloaded_worker["current_job_id"])

    def test_heartbeat_worker_rejects_expired_busy_worker(self) -> None:
        created_job = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
        )
        registered_worker = worker.register_worker()
        claimed = worker.claim_next_job(registered_worker["worker_id"])
        self.assertEqual(claimed["job_id"], created_job["job_id"])

        worker.update_worker(
            registered_worker["worker_id"],
            lease_expires_at=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
        )

        with self.assertRaisesRegex(
            ValueError,
            f"Worker `{registered_worker['worker_id']}` lease expired while holding job `{created_job['job_id']}`",
        ):
            worker.heartbeat_worker(registered_worker["worker_id"])

    def test_cancel_job_execution_releases_worker_for_running_job(self) -> None:
        created_job = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
        )
        registered_worker = worker.register_worker()
        claimed = worker.claim_next_job(registered_worker["worker_id"])

        canceled = worker.cancel_job_execution(claimed["job_id"], reason="operator canceled")

        self.assertEqual(canceled["job_id"], created_job["job_id"])
        self.assertEqual(canceled["status"], "canceled")
        self.assertEqual(canceled["cancel_reason"], "operator canceled")
        self.assertEqual(worker.load_worker(registered_worker["worker_id"])["status"], "idle")
        self.assertIsNone(worker.load_worker(registered_worker["worker_id"])["current_job_id"])

    def test_run_claimed_job_returns_canceled_job_without_dispatch(self) -> None:
        created_job = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
        )
        registered_worker = worker.register_worker()
        claimed = worker.claim_next_job(registered_worker["worker_id"])
        worker.cancel_job_execution(claimed["job_id"], reason="operator canceled")

        with patch.object(worker, "dispatch_job") as mock_dispatch_job:
            canceled = worker.run_claimed_job(registered_worker["worker_id"], claimed["job_id"])

        self.assertEqual(canceled["job_id"], created_job["job_id"])
        self.assertEqual(canceled["status"], "canceled")
        mock_dispatch_job.assert_not_called()
        self.assertEqual(worker.load_worker(registered_worker["worker_id"])["status"], "idle")


if __name__ == "__main__":
    unittest.main()
