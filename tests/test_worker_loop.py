import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime.queue as queue
import runtime.worker as worker
import runtime.worker_loop as worker_loop


class WorkerLoopTests(unittest.TestCase):
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

    @patch.object(worker, "start_workflow", return_value={"workflow_id": "wf-123", "status": "succeeded"})
    def test_run_worker_loop_processes_job_and_returns_summary(self, _mock_start_workflow) -> None:
        created_job = queue.create_job(
            job_type="workflow_start",
            payload={"input": "hello", "agent": "default"},
        )

        summary = worker_loop.run_worker_loop(
            worker_name="packaged-worker",
            poll_seconds=0,
            max_jobs=1,
            repair_orphans_on_start=False,
            sleep_fn=lambda _seconds: None,
        )

        self.assertEqual(summary["processed_jobs"], 1)
        self.assertEqual(summary["error_count"], 0)
        self.assertEqual(summary["worker"]["name"], "packaged-worker")
        self.assertEqual(summary["worker"]["status"], "idle")
        self.assertEqual(queue.load_job(created_job["job_id"])["status"], "completed")

    def test_run_worker_loop_stops_after_idle_polls(self) -> None:
        summary = worker_loop.run_worker_loop(
            worker_name="idle-worker",
            poll_seconds=0,
            max_idle_polls=2,
            repair_orphans_on_start=False,
            sleep_fn=lambda _seconds: None,
        )

        self.assertEqual(summary["processed_jobs"], 0)
        self.assertEqual(summary["idle_polls"], 2)
        self.assertEqual(summary["error_count"], 0)
        self.assertEqual(summary["worker"]["status"], "idle")
