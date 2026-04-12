import itertools
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import runtime.approval as approval
import runtime.artifact as artifact
import runtime.control_plane as control_plane
import runtime.email_intake as email_intake
import runtime.memory as memory
import runtime.queue as queue
import runtime.session as session
import runtime.trace as trace
import runtime.worker as worker
import runtime.workflow as workflow
import runtime.workflow_runner as workflow_runner


class ReleaseValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.approval_dir = self.root_dir / "approvals"
        self.artifact_dir = self.root_dir / "artifacts"
        self.memory_dir = self.root_dir / "memories"
        self.job_dir = self.root_dir / "jobs"
        self.log_dir = self.root_dir / "logs"
        self.session_dir = self.root_dir / "sessions"
        self.worker_dir = self.root_dir / "workers"
        self.workflow_dir = self.root_dir / "workflows"
        self.approval_dir.mkdir()
        self.artifact_dir.mkdir()
        self.memory_dir.mkdir()
        self.job_dir.mkdir()
        self.log_dir.mkdir()
        self.session_dir.mkdir()
        self.worker_dir.mkdir()
        self.workflow_dir.mkdir()
        self.patchers = [
            patch.object(approval, "APPROVAL_DIR", self.approval_dir),
            patch.object(artifact, "ARTIFACT_DIR", self.artifact_dir),
            patch.object(memory, "MEMORY_DIR", self.memory_dir),
            patch.object(queue, "JOB_DIR", self.job_dir),
            patch.object(session, "SESSION_DIR", self.session_dir),
            patch.object(trace, "LOG_DIR", self.log_dir),
            patch.object(worker, "WORKER_DIR", self.worker_dir),
            patch.object(workflow, "WORKFLOW_DIR", self.workflow_dir),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.workflow_counter = itertools.count()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def build_successful_workflow_result(
        self,
        *,
        user_input: str,
        agent_name: str,
        tool_name: str | None = None,
        tool_args: dict | None = None,
        approval_id: str | None = None,
        job_id: str | None = None,
        worker_id: str | None = None,
    ) -> dict:
        index = next(self.workflow_counter)
        run_id = f"wf-load-{index}"
        state = workflow.create_workflow_state(
            run_id=run_id,
            agent=agent_name,
            run_type="tool" if tool_name is not None else "model",
            request={
                "input": user_input,
                "agent": agent_name,
                "tool": tool_name,
                "tool_args": tool_args,
                "approval_id": approval_id,
            },
        )
        workflow.complete_workflow(state)
        workflow.write_workflow(state)
        return {
            "status": "success",
            "job_id": job_id,
            "worker_id": worker_id,
            "workflow": workflow.workflow_snapshot(state),
        }

    def test_soak_drill_processes_batched_jobs_across_workers(self) -> None:
        total_jobs = 12
        for index in range(total_jobs):
            queue.create_job(
                job_type="workflow_start",
                payload={"input": f"load-{index}", "agent": "default"},
                priority=100 - index,
            )

        workers = [
            worker.register_worker(name="queue-a"),
            worker.register_worker(name="queue-b"),
        ]

        with patch.object(worker, "start_workflow", side_effect=self.build_successful_workflow_result):
            progressed = True
            while progressed:
                progressed = False
                for current in workers:
                    result = worker.run_next_job(current["worker_id"])
                    if result is not None:
                        progressed = True

        completed_jobs = queue.list_jobs(status="completed")
        queue_health = queue.queue_health_summary()
        worker_health = worker.worker_health_summary()

        self.assertEqual(len(completed_jobs), total_jobs)
        self.assertEqual(queue_health["counts"]["completed"], total_jobs)
        self.assertEqual(queue_health["health"]["retry_backlog_count"], 0)
        self.assertEqual(queue_health["health"]["expired_running_count"], 0)
        self.assertEqual(worker_health["counts"]["idle"], len(workers))
        self.assertEqual(worker_health["counts"]["busy"], 0)
        self.assertEqual(len(list(self.workflow_dir.glob("*.json"))), total_jobs)

    def test_batch_recovery_and_replay_drill(self) -> None:
        failed_workflow_ids = []
        for index in range(3):
            state = workflow.create_workflow_state(
                run_id=f"wf-failed-{index}",
                agent="default",
                run_type="model",
                request={
                    "input": f"recover-{index}",
                    "agent": "default",
                    "tool": None,
                    "tool_args": None,
                },
            )
            workflow.fail_workflow(state, error_type="RuntimeError", message=f"boom-{index}")
            workflow.write_workflow(state)

            failed_job = queue.create_job(
                job_type="workflow_resume",
                payload={"workflow_id": state.workflow_id, "input": "", "agent": "default"},
                workflow_id=state.workflow_id,
            )
            queue.update_job(
                failed_job["job_id"],
                status="failed",
                error={"type": "RuntimeError", "message": f"boom-{index}"},
            )

            dead_job = queue.create_job(
                job_type="workflow_resume",
                payload={"workflow_id": state.workflow_id, "input": "", "agent": "default"},
                workflow_id=state.workflow_id,
            )
            queue.update_job(
                dead_job["job_id"],
                status="dead_letter",
                dead_lettered_at="2026-01-01T00:00:00+00:00",
            )

            registered_worker = worker.register_worker(name=f"recover-{index}")
            expired_at = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
            running_job = queue.create_job(
                job_type="workflow_resume",
                payload={"workflow_id": state.workflow_id, "input": "", "agent": "default"},
                workflow_id=state.workflow_id,
            )
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

            if index == 0:
                incident = control_plane.workflow_incident_summary_view(state.workflow_id)
                self.assertEqual(
                    incident["recovery"]["expired_running_job_ids"],
                    [running_job["job_id"]],
                )
                self.assertEqual(
                    sorted(incident["recovery"]["recoverable_job_ids"]),
                    sorted([failed_job["job_id"], dead_job["job_id"]]),
                )

            recovered = control_plane.recover_workflow(
                state.workflow_id,
                reclaim_expired_jobs=True,
                reschedule_failed_jobs=True,
                reschedule_dead_letter_jobs=True,
            )
            self.assertEqual(recovered["reclaimed_count"], 1)
            self.assertEqual(recovered["rescheduled_count"], 2)
            failed_workflow_ids.append(state.workflow_id)

        replay_counter = itertools.count()

        def successful_replay(**kwargs) -> dict:
            return {
                "status": "success",
                "workflow": {"workflow_id": f"wf-replayed-{next(replay_counter)}"},
                "job_id": kwargs.get("job_id"),
                "worker_id": kwargs.get("worker_id"),
            }

        with patch.object(workflow_runner, "run_agent", side_effect=successful_replay):
            for workflow_id in failed_workflow_ids:
                replayed = workflow_runner.replay_workflow(workflow_id)
                self.assertEqual(replayed["source_status"], "failed")
                self.assertEqual(replayed["result"]["status"], "success")

    def test_email_triage_intake_to_draft_approval_drill(self) -> None:
        workflow_state = workflow.create_workflow_state(
            run_id="wf-email-release",
            agent="researcher",
            run_type="model",
            request={
                "input": "Review this email for narrow triage.",
                "agent": "researcher",
                "tool": None,
                "tool_args": None,
            },
        )
        workflow.complete_workflow(workflow_state)
        workflow.write_workflow(workflow_state)

        def fake_append_session_message(session_id: str, **_kwargs) -> dict:
            return {
                "session": session.session_snapshot(session.load_session(session_id)),
                "workflow_result": {
                    "status": "success",
                    "output": (
                        "Bottom line: Resend the invoice.\n"
                        "Urgency: Medium\n"
                        "Suggested bucket: Billing\n"
                        "Recommended next action: Confirm the invoice number and resend it today.\n"
                        "Draft reply: Hi Alex,\nWe can resend that invoice today."
                    ),
                    "workflow": workflow.workflow_snapshot(workflow_state),
                    "artifacts": [],
                },
            }

        with patch.object(email_intake, "append_session_message", side_effect=fake_append_session_message):
            intake_result = email_intake.intake_email(
                {
                    "account": "ops@example.com",
                    "mailbox": "inbox",
                    "thread_id": "thread-123",
                    "message_id": "msg-123",
                    "subject": "Need invoice copy",
                    "from": "Alex <alex@example.com>",
                    "to": ["ops@example.com"],
                    "received_at": "2026-04-12T10:00:00+00:00",
                    "text_body": "Please resend the invoice PDF.",
                },
                agent="researcher",
            )

        triage_artifact = artifact.load_artifact(intake_result["triage_artifact"]["artifact_id"])
        self.assertEqual(triage_artifact["kind"], "email_triage")
        self.assertEqual(
            triage_artifact["value"]["triage"]["fields"]["recommended_next_action"],
            "Confirm the invoice number and resend it today.",
        )

        approval_request = email_intake.request_email_draft_approval(triage_artifact["artifact_id"])
        self.assertEqual(approval_request["status"], "pending")
        approved = approval.approve_approval(approval_request["approval_id"])
        self.assertEqual(approved["status"], "approved")
        handoff = email_intake.create_email_draft_handoff(triage_artifact["artifact_id"])
        self.assertEqual(handoff["kind"], "email_draft_handoff")

        workflow_view = control_plane.workflow_control_view(workflow_state.workflow_id)
        self.assertEqual(workflow_view["email_triage"]["approval"]["status"], "approved")
        self.assertEqual(workflow_view["email_triage"]["approval_outcome"], "Approved handoff ready")
        self.assertEqual(workflow_view["email_triage"]["approved_handoff"]["artifact_id"], handoff["artifact_id"])
        self.assertIn("manual follow-through", workflow_view["email_triage"]["operator_next_step"])
        self.assertIn("automatic send behavior remains out of scope", workflow_view["email_triage"]["outward_action_detail"])

        retry_state = workflow.create_workflow_state(
            run_id="wf-retry-drill",
            agent="default",
            run_type="model",
            request={"input": "retry", "agent": "default", "tool": None, "tool_args": None},
        )
        workflow.configure_retry_policy(retry_state, {"max_attempts": 1, "backoff_seconds": 0})
        workflow.wait_for_retry(
            retry_state,
            error_type="RuntimeError",
            message="temporary failure",
            retryable=True,
        )
        workflow.write_workflow(retry_state)

        with patch.object(workflow_runner, "run_agent", return_value={"status": "success"}) as mock_run_agent:
            resumed = workflow_runner.safe_resume_workflow(retry_state.workflow_id)

        queue_health = queue.queue_health_summary()
        worker_health = worker.worker_health_summary()

        self.assertEqual(resumed["status"], "success")
        mock_run_agent.assert_called_once()
        self.assertEqual(queue_health["health"]["expired_running_count"], 0)
        self.assertEqual(worker_health["counts"]["busy"], 0)


if __name__ == "__main__":
    unittest.main()
