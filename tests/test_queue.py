import json
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

    def test_create_job_persists_versioned_state_envelope(self) -> None:
        job = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
        )

        with (self.job_dir / f"{job['job_id']}.json").open(encoding="utf-8") as file:
            saved = json.load(file)

        self.assertEqual(saved["schema"], "job.v1")
        self.assertEqual(saved["version"], "v0.9")
        self.assertEqual(saved["payload"]["job_id"], job["job_id"])

    def test_job_updates_append_transition_history(self) -> None:
        job = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
        )

        queue.update_job(
            job["job_id"],
            status="running",
            worker_id="worker-123",
            claimed_at="2026-01-01T00:00:00+00:00",
            lease_expires_at="2026-01-01T00:00:30+00:00",
            transition_reason="claimed_by_worker:worker-123",
        )
        loaded = queue.load_job(job["job_id"])
        event_types = [entry["event_type"] for entry in loaded["transition_history"]]

        self.assertIn("created", event_types)
        self.assertIn("claimed", event_types)
        self.assertEqual(loaded["transition_history"][-1]["reason"], "claimed_by_worker:worker-123")

    def test_load_job_accepts_legacy_unversioned_snapshot(self) -> None:
        legacy_job = {
            "job_id": "legacy-job",
            "job_type": "workflow_start",
            "status": "queued",
            "priority": 100,
            "ready_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"input": "hello", "agent": "default"},
            "workflow_id": None,
            "parent_job_id": None,
            "idempotency_key": None,
            "worker_id": None,
            "claimed_at": None,
            "lease_expires_at": None,
            "reclaim_count": 0,
            "last_requeue_reason": None,
            "attempt_count": 0,
            "max_attempts": 1,
            "retry_backoff_seconds": 30,
            "last_failure_at": None,
            "next_retry_at": None,
            "dead_lettered_at": None,
            "canceled_at": None,
            "cancel_reason": None,
            "result": None,
            "error": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "lease_expired": False,
        }

        with (self.job_dir / "legacy-job.json").open("w", encoding="utf-8") as file:
            json.dump(legacy_job, file, indent=2)

        loaded = queue.load_job("legacy-job")

        self.assertEqual(loaded["job_id"], "legacy-job")
        self.assertEqual(loaded["status"], "queued")

    def test_list_jobs_supports_mixed_legacy_and_versioned_snapshots(self) -> None:
        versioned = queue.create_job(
            job_type="workflow_start",
            payload={"input": "new", "agent": "default"},
            priority=20,
        )
        legacy_job = {
            "job_id": "legacy-job",
            "job_type": "workflow_start",
            "status": "queued",
            "priority": 10,
            "ready_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"input": "legacy", "agent": "default"},
            "workflow_id": None,
            "parent_job_id": None,
            "idempotency_key": "legacy-key",
            "worker_id": None,
            "claimed_at": None,
            "lease_expires_at": None,
            "reclaim_count": 0,
            "last_requeue_reason": None,
            "attempt_count": 0,
            "max_attempts": 1,
            "retry_backoff_seconds": 30,
            "last_failure_at": None,
            "next_retry_at": None,
            "dead_lettered_at": None,
            "canceled_at": None,
            "cancel_reason": None,
            "result": None,
            "error": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "lease_expired": False,
        }
        with (self.job_dir / "legacy-job.json").open("w", encoding="utf-8") as file:
            json.dump(legacy_job, file, indent=2)

        jobs = queue.list_jobs(promote_due=False)
        found = {job["job_id"] for job in jobs}

        self.assertIn(versioned["job_id"], found)
        self.assertIn("legacy-job", found)

    def test_record_job_failure_rewrites_legacy_snapshot_as_versioned_state(self) -> None:
        legacy_job = {
            "job_id": "legacy-job",
            "job_type": "workflow_start",
            "status": "running",
            "priority": 100,
            "ready_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"input": "legacy", "agent": "default"},
            "workflow_id": None,
            "parent_job_id": None,
            "idempotency_key": None,
            "worker_id": "worker-123",
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "lease_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
            "reclaim_count": 0,
            "last_requeue_reason": None,
            "attempt_count": 0,
            "max_attempts": 1,
            "retry_backoff_seconds": 30,
            "last_failure_at": None,
            "next_retry_at": None,
            "dead_lettered_at": None,
            "canceled_at": None,
            "cancel_reason": None,
            "result": None,
            "error": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "lease_expired": False,
        }
        path = self.job_dir / "legacy-job.json"
        with path.open("w", encoding="utf-8") as file:
            json.dump(legacy_job, file, indent=2)

        failed = queue.record_job_failure("legacy-job", exc=RuntimeError("boom"))

        self.assertEqual(failed["status"], "failed")
        with path.open(encoding="utf-8") as file:
            saved = json.load(file)
        self.assertEqual(saved["schema"], "job.v1")

    def test_repair_stale_job_state_clears_claim_fields_and_promotes_due_jobs(self) -> None:
        queued = queue.create_job(
            job_type="workflow_start",
            payload={"input": "queued", "agent": "default"},
        )
        queue.update_job(
            queued["job_id"],
            status="queued",
            worker_id="worker-123",
            claimed_at="2026-01-01T00:00:00+00:00",
            lease_expires_at="2026-01-01T00:00:30+00:00",
        )

        scheduled = queue.create_job(
            job_type="workflow_start",
            payload={"input": "scheduled", "agent": "default"},
            delay_seconds=60,
        )
        queue.update_job(
            scheduled["job_id"],
            status="scheduled",
            ready_at=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
            worker_id="worker-456",
            claimed_at="2026-01-01T00:00:00+00:00",
            lease_expires_at="2026-01-01T00:00:30+00:00",
        )

        repaired = queue.repair_stale_job_state()

        self.assertEqual(repaired["repaired_count"], 2)
        reloaded_queued = queue.load_job(queued["job_id"])
        self.assertEqual(reloaded_queued["status"], "queued")
        self.assertIsNone(reloaded_queued["worker_id"])
        self.assertIsNone(reloaded_queued["claimed_at"])
        self.assertIsNone(reloaded_queued["lease_expires_at"])
        reloaded_scheduled = queue.load_job(scheduled["job_id"])
        self.assertEqual(reloaded_scheduled["status"], "queued")
        self.assertIsNone(reloaded_scheduled["worker_id"])

    def test_prune_jobs_removes_old_dead_letter_jobs_by_default(self) -> None:
        old_timestamp = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        dead_letter_job = {
            "job_id": "dead-letter-job",
            "job_type": "workflow_resume",
            "status": "dead_letter",
            "priority": 100,
            "ready_at": old_timestamp,
            "payload": {"workflow_id": "wf-123", "input": "", "agent": "default"},
            "workflow_id": "wf-123",
            "parent_job_id": None,
            "idempotency_key": None,
            "worker_id": None,
            "claimed_at": None,
            "lease_expires_at": None,
            "reclaim_count": 0,
            "last_requeue_reason": None,
            "attempt_count": 1,
            "max_attempts": 2,
            "retry_backoff_seconds": 30,
            "last_failure_at": old_timestamp,
            "next_retry_at": None,
            "dead_lettered_at": old_timestamp,
            "canceled_at": None,
            "cancel_reason": None,
            "result": None,
            "error": {"type": "RuntimeError", "message": "boom"},
            "created_at": old_timestamp,
            "updated_at": old_timestamp,
        }
        failed_job = {
            **dead_letter_job,
            "job_id": "failed-job",
            "status": "failed",
            "dead_lettered_at": None,
        }
        with (self.job_dir / "dead-letter-job.json").open("w", encoding="utf-8") as file:
            json.dump(dead_letter_job, file, indent=2)
        with (self.job_dir / "failed-job.json").open("w", encoding="utf-8") as file:
            json.dump(failed_job, file, indent=2)

        pruned = queue.prune_jobs(older_than_seconds=3600)

        self.assertEqual(pruned["pruned_job_ids"], ["dead-letter-job"])
        self.assertFalse((self.job_dir / "dead-letter-job.json").exists())
        self.assertTrue((self.job_dir / "failed-job.json").exists())

    def test_queue_health_summary_reports_ages_retry_backlog_and_expired_running_jobs(self) -> None:
        queued = queue.create_job(
            job_type="workflow_start",
            payload={"input": "queued", "agent": "default"},
        )
        queue.update_job(
            queued["job_id"],
            created_at=(datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(),
        )

        retry_job = queue.create_job(
            job_type="workflow_resume",
            payload={"workflow_id": "wf-123", "input": "", "agent": "default"},
            workflow_id="wf-123",
            delay_seconds=60,
        )
        queue.update_job(
            retry_job["job_id"],
            status="scheduled",
            attempt_count=1,
            next_retry_at=(datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
            ready_at=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
        )

        running = queue.create_job(
            job_type="workflow_start",
            payload={"input": "running", "agent": "default"},
        )
        queue.update_job(
            running["job_id"],
            status="running",
            worker_id="worker-123",
            claimed_at=(datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat(),
            lease_expires_at=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
        )

        health = queue.queue_health_summary()

        self.assertEqual(health["health"]["retry_backlog_count"], 1)
        self.assertEqual(health["health"]["expired_running_job_ids"], [running["job_id"]])
        self.assertGreaterEqual(health["health"]["oldest_queued_age_seconds"], 100)
        self.assertGreaterEqual(health["health"]["oldest_retry_age_seconds"], 20)
        self.assertGreaterEqual(health["health"]["max_running_claim_age_seconds"], 40)
        self.assertEqual(health["health"]["trends"]["recent_failures_last_hour"], 0)
        self.assertEqual(health["health"]["trends"]["recent_retries_last_hour"], 1)
        self.assertEqual(health["health"]["trends"]["reclaimed_jobs_total"], 0)
        self.assertIn("retry_pending", [event["event_type"] for event in health["health"]["trends"]["recent_events"]])
        self.assertGreaterEqual(health["health"]["lifecycle"]["counts"]["retry_scheduled"], 1)
        self.assertGreaterEqual(health["health"]["lifecycle"]["counts"]["claimed"], 1)
        self.assertIn(
            "retry_scheduled",
            [event["event_type"] for event in health["health"]["lifecycle"]["recent_events"]],
        )

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
