import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import runtime.queue as queue


class QueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.job_dir = self.root_dir / "jobs"
        self.job_dir.mkdir()
        self.job_dir_patcher = patch.object(queue, "JOB_DIR", self.job_dir)
        self.job_dir_patcher.start()

    def tearDown(self) -> None:
        self.job_dir_patcher.stop()
        self.temp_dir.cleanup()

    def test_create_job_immediate_is_queued(self) -> None:
        job = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
            priority=50,
        )

        self.assertEqual(job["job_type"], "workflow_start")
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["priority"], 50)
        loaded = queue.load_job(job["job_id"])
        self.assertEqual(loaded["job_id"], job["job_id"])

    def test_create_job_with_delay_is_scheduled(self) -> None:
        job = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
            delay_seconds=60,
        )

        self.assertEqual(job["status"], "scheduled")
        self.assertGreater(
            datetime.fromisoformat(job["ready_at"]),
            datetime.now(timezone.utc),
        )

    def test_list_jobs_orders_queued_before_scheduled_and_by_priority(self) -> None:
        future_job = queue.create_job(
            job_type="workflow_start",
            payload={"input": "later", "agent": "default"},
            priority=10,
            delay_seconds=60,
        )
        low_priority = queue.create_job(
            job_type="workflow_start",
            payload={"input": "low", "agent": "default"},
            priority=10,
        )
        high_priority = queue.create_job(
            job_type="workflow_start",
            payload={"input": "high", "agent": "default"},
            priority=100,
        )

        jobs = queue.list_jobs()

        self.assertEqual(
            [job["job_id"] for job in jobs],
            [high_priority["job_id"], low_priority["job_id"], future_job["job_id"]],
        )

    def test_load_job_materializes_ready_scheduled_job_as_queued(self) -> None:
        ready_at = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        job = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
            run_at=ready_at,
        )

        loaded = queue.load_job(job["job_id"])

        self.assertEqual(loaded["status"], "queued")

    def test_create_job_reuses_matching_idempotency_key(self) -> None:
        created = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
            idempotency_key="job-key-123",
        )

        reused = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
            idempotency_key="job-key-123",
        )

        self.assertEqual(reused["job_id"], created["job_id"])
        self.assertEqual(len(queue.list_jobs()), 1)

    def test_create_job_rejects_conflicting_idempotency_key(self) -> None:
        queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
            idempotency_key="job-key-123",
        )

        with self.assertRaisesRegex(
            ValueError,
            "Idempotency key `job-key-123` is already used by a different job request",
        ):
            queue.create_job(
                job_type="workflow_start",
                payload={"input": "different", "agent": "default"},
                idempotency_key="job-key-123",
            )

    def test_cancel_job_marks_queued_job_canceled(self) -> None:
        created = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
        )

        canceled = queue.cancel_job(created["job_id"], reason="operator canceled")

        self.assertEqual(canceled["status"], "canceled")
        self.assertEqual(canceled["cancel_reason"], "operator canceled")
        self.assertIsNotNone(canceled["canceled_at"])

    def test_promote_due_jobs_persists_scheduled_job_to_queued(self) -> None:
        ready_at = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        created = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
            run_at=ready_at,
        )
        queue.update_job(created["job_id"], status="scheduled")

        promoted = queue.promote_due_jobs()

        self.assertEqual(promoted["promoted_count"], 1)
        self.assertEqual(promoted["promoted_job_ids"], [created["job_id"]])
        self.assertEqual(queue.load_job(created["job_id"])["status"], "queued")

    def test_queue_summary_reports_counts_and_next_ready_job(self) -> None:
        queued = queue.create_job(
            job_type="workflow_start",
            payload={"input": "queued", "agent": "default"},
        )
        scheduled = queue.create_job(
            job_type="workflow_start",
            payload={"input": "later", "agent": "default"},
            delay_seconds=60,
        )

        summary = queue.queue_summary()

        self.assertEqual(summary["counts"]["queued"], 1)
        self.assertEqual(summary["counts"]["scheduled"], 1)
        self.assertEqual(summary["queued_job_ids"], [queued["job_id"]])
        self.assertEqual(summary["next_ready_at"], scheduled["ready_at"])
        self.assertEqual(summary["promoted_count"], 0)

    def test_reschedule_job_moves_queued_job_to_scheduled(self) -> None:
        created = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
        )

        rescheduled = queue.reschedule_job(created["job_id"], delay_seconds=120)

        self.assertEqual(rescheduled["status"], "scheduled")
        self.assertGreater(
            datetime.fromisoformat(rescheduled["ready_at"]),
            datetime.now(timezone.utc),
        )

    def test_record_job_failure_schedules_retry_before_dead_letter(self) -> None:
        created = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
            max_attempts=3,
            retry_backoff_seconds=10,
        )
        queue.update_job(
            created["job_id"],
            status="running",
            worker_id="worker-123",
            claimed_at=datetime.now(timezone.utc).isoformat(),
            lease_expires_at=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
        )

        failed = queue.record_job_failure(created["job_id"], exc=RuntimeError("boom"))

        self.assertEqual(failed["status"], "scheduled")
        self.assertEqual(failed["attempt_count"], 1)
        self.assertEqual(failed["error"]["message"], "boom")
        self.assertEqual(failed["last_requeue_reason"], "Retry 1 scheduled after failure")
        self.assertIsNotNone(failed["next_retry_at"])

    def test_record_job_failure_dead_letters_after_attempts_exhausted(self) -> None:
        created = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
            max_attempts=2,
            retry_backoff_seconds=0,
        )
        queue.update_job(created["job_id"], status="running", worker_id="worker-123")
        queue.record_job_failure(created["job_id"], exc=RuntimeError("boom"))
        queue.update_job(created["job_id"], status="running", worker_id="worker-123")

        failed = queue.record_job_failure(created["job_id"], exc=RuntimeError("boom again"))

        self.assertEqual(failed["status"], "dead_letter")
        self.assertEqual(failed["attempt_count"], 2)
        self.assertEqual(failed["error"]["message"], "boom again")
        self.assertIsNotNone(failed["dead_lettered_at"])

    def test_queue_summary_reports_retry_and_dead_letter_metrics(self) -> None:
        retrying = queue.create_job(
            job_type="workflow_start",
            payload={"input": "retry", "agent": "default"},
            max_attempts=3,
            retry_backoff_seconds=10,
        )
        queue.update_job(retrying["job_id"], status="running", worker_id="worker-1")
        queue.record_job_failure(retrying["job_id"], exc=RuntimeError("retry me"))

        dead = queue.create_job(
            job_type="workflow_start",
            payload={"input": "dead", "agent": "default"},
            max_attempts=2,
            retry_backoff_seconds=0,
        )
        queue.update_job(dead["job_id"], status="running", worker_id="worker-2")
        queue.record_job_failure(dead["job_id"], exc=RuntimeError("boom"))
        queue.update_job(dead["job_id"], status="running", worker_id="worker-2")
        queue.record_job_failure(dead["job_id"], exc=RuntimeError("boom again"))

        summary = queue.queue_summary()

        self.assertEqual(summary["retry_pending_count"], 1)
        self.assertEqual(summary["dead_letter_count"], 1)
        self.assertEqual(summary["retry_scheduled_job_ids"], [retrying["job_id"]])
        self.assertEqual(summary["dead_letter_job_ids"], [dead["job_id"]])


if __name__ == "__main__":
    unittest.main()
