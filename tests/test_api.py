import json
import unittest
from unittest.mock import patch

import api.main as main
from runtime.errors import ApprovalStateError, BudgetExceededError, PolicyDeniedError


class ApiTests(unittest.TestCase):
    @patch.object(main, "register_worker", return_value={"worker_id": "worker-123", "status": "idle"})
    def test_worker_create_passthrough(self, mock_register_worker) -> None:
        response = main.worker_create({"name": "queue-1", "lease_seconds": 45})

        self.assertEqual(response["worker_id"], "worker-123")
        mock_register_worker.assert_called_once_with(name="queue-1", lease_seconds=45)

    @patch.object(main, "list_workers", return_value=[{"worker_id": "worker-123"}])
    def test_worker_list_passthrough(self, mock_list_workers) -> None:
        response = main.worker_list()

        self.assertEqual(response["workers"], [{"worker_id": "worker-123"}])
        mock_list_workers.assert_called_once_with()

    @patch.object(main, "load_worker", return_value={"worker_id": "worker-123", "status": "idle"})
    def test_worker_status_passthrough(self, _mock_load_worker) -> None:
        response = main.worker_status("worker-123")

        self.assertEqual(response["worker_id"], "worker-123")
        self.assertEqual(response["status"], "idle")

    @patch.object(main, "heartbeat_worker", return_value={"worker_id": "worker-123", "status": "idle"})
    def test_worker_heartbeat_passthrough(self, mock_heartbeat_worker) -> None:
        response = main.worker_heartbeat("worker-123")

        self.assertEqual(response["worker_id"], "worker-123")
        mock_heartbeat_worker.assert_called_once_with("worker-123")

    @patch.object(main, "claim_next_job", return_value={"job_id": "job-123", "status": "running"})
    def test_worker_claim_job_passthrough(self, mock_claim_next_job) -> None:
        response = main.worker_claim_job("worker-123")

        self.assertEqual(response["job"]["job_id"], "job-123")
        mock_claim_next_job.assert_called_once_with("worker-123")

    @patch.object(main, "run_claimed_job", return_value={"job_id": "job-123", "status": "completed"})
    def test_worker_run_claimed_job_passthrough(self, mock_run_claimed_job) -> None:
        response = main.worker_run_claimed_job("worker-123", "job-123")

        self.assertEqual(response["job_id"], "job-123")
        mock_run_claimed_job.assert_called_once_with("worker-123", "job-123")

    @patch.object(main, "run_next_job", return_value={"job_id": "job-123", "status": "completed"})
    def test_worker_run_next_passthrough(self, mock_run_next_job) -> None:
        response = main.worker_run_next("worker-123")

        self.assertEqual(response["job"]["job_id"], "job-123")
        mock_run_next_job.assert_called_once_with("worker-123")

    @patch.object(main, "reclaim_expired_leases", return_value={"reclaimed_count": 1})
    def test_worker_reclaim_expired_passthrough(self, mock_reclaim_expired_leases) -> None:
        response = main.worker_reclaim_expired()

        self.assertEqual(response["reclaimed_count"], 1)
        mock_reclaim_expired_leases.assert_called_once_with()

    @patch.object(main, "create_job", return_value={"job_id": "job-123", "status": "queued"})
    def test_job_create_passthrough(self, mock_create_job) -> None:
        response = main.job_create(
            {
                "type": "workflow_start",
                "input": "hello",
                "max_attempts": 3,
                "retry_backoff_seconds": 15,
            }
        )

        self.assertEqual(response["job_id"], "job-123")
        mock_create_job.assert_called_once_with(
            job_type="workflow_start",
            payload={
                "input": "hello",
                "agent": "default",
                "tool": None,
                "tool_args": None,
                "approval_id": None,
            },
            priority=100,
            delay_seconds=0,
            run_at=None,
            workflow_id=None,
            parent_job_id=None,
            idempotency_key=None,
            max_attempts=3,
            retry_backoff_seconds=15,
        )

    def test_job_create_requires_workflow_id_for_resume_jobs(self) -> None:
        response = main.job_create({"type": "workflow_resume"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.body),
            {
                "status": "error",
                "error": {
                    "type": "ValueError",
                    "message": "Job type `workflow_resume` requires `workflow_id`",
                },
            },
        )

    @patch.object(main, "list_jobs", return_value=[{"job_id": "job-123"}])
    def test_job_list_passthrough(self, mock_list_jobs) -> None:
        response = main.job_list(status="queued")

        self.assertEqual(response["jobs"], [{"job_id": "job-123"}])
        mock_list_jobs.assert_called_once_with(status="queued")

    @patch.object(main, "load_job", return_value={"job_id": "job-123", "status": "queued"})
    def test_job_status_passthrough(self, _mock_load_job) -> None:
        response = main.job_status("job-123")

        self.assertEqual(response["job_id"], "job-123")
        self.assertEqual(response["status"], "queued")

    @patch.object(main, "cancel_job_execution", return_value={"job_id": "job-123", "status": "canceled"})
    def test_job_cancel_passthrough(self, mock_cancel_job_execution) -> None:
        response = main.job_cancel("job-123", {"reason": "operator canceled"})

        self.assertEqual(response["job_id"], "job-123")
        self.assertEqual(response["status"], "canceled")
        mock_cancel_job_execution.assert_called_once_with("job-123", reason="operator canceled")

    @patch.object(main, "reschedule_job", return_value={"job_id": "job-123", "status": "scheduled"})
    def test_job_reschedule_passthrough(self, mock_reschedule_job) -> None:
        response = main.job_reschedule("job-123", {"delay_seconds": 60})

        self.assertEqual(response["job_id"], "job-123")
        self.assertEqual(response["status"], "scheduled")
        mock_reschedule_job.assert_called_once_with("job-123", delay_seconds=60, run_at=None)

    @patch.object(
        main,
        "queue_summary",
        return_value={"counts": {"queued": 1, "scheduled": 0}},
    )
    def test_queue_status_passthrough(self, mock_queue_summary) -> None:
        response = main.queue_status()

        self.assertEqual(response["counts"]["queued"], 1)
        mock_queue_summary.assert_called_once_with()

    @patch.object(main, "promote_due_jobs", return_value={"promoted_count": 1, "promoted_job_ids": ["job-123"]})
    def test_queue_promote_ready_passthrough(self, mock_promote_due_jobs) -> None:
        response = main.queue_promote_ready({"limit": 5})

        self.assertEqual(response["promoted_count"], 1)
        mock_promote_due_jobs.assert_called_once_with(limit=5)

    @patch.object(main, "start_workflow")
    def test_run_success_passthrough(self, mock_start_workflow) -> None:
        mock_start_workflow.return_value = {
            "status": "success",
            "run_type": "tool",
            "agent": "default",
            "prompt": None,
            "provider": None,
            "model": None,
            "tool": "echo",
            "tool_args": {"text": "hello"},
            "tool_output": "hello",
            "output": "hello",
        }

        response = main.run(
            {"agent": "default", "tool": "echo", "tool_args": {"text": "hello"}}
        )

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["run_type"], "tool")
        self.assertEqual(response["tool_output"], "hello")

    @patch.object(main, "start_workflow", side_effect=ValueError("bad input"))
    def test_run_value_error_returns_400(self, _mock_start_workflow) -> None:
        response = main.run({"agent": "default"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.body),
            {
                "status": "error",
                "error": {
                    "type": "ValueError",
                    "message": "bad input",
                },
            },
        )

    @patch.object(main, "start_workflow", side_effect=FileNotFoundError("missing file"))
    def test_run_missing_file_returns_404(self, _mock_start_workflow) -> None:
        response = main.run({"agent": "default"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            json.loads(response.body),
            {
                "status": "error",
                "error": {
                    "type": "FileNotFoundError",
                    "message": "missing file",
                },
            },
        )

    @patch.object(main, "start_workflow", side_effect=RuntimeError("boom"))
    def test_run_runtime_error_returns_500(self, _mock_start_workflow) -> None:
        response = main.run({"agent": "default"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            json.loads(response.body),
            {
                "status": "error",
                "error": {
                    "type": "RuntimeError",
                    "message": "boom",
                },
            },
        )

    @patch.object(
        main,
        "start_workflow",
        side_effect=PolicyDeniedError(
            "policy says no",
            capability="model_call",
            policy_name="safe_readonly",
        ),
    )
    def test_run_policy_denied_returns_403(self, _mock_start_workflow) -> None:
        response = main.run({"agent": "default"})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            json.loads(response.body),
            {
                "status": "error",
                "error": {
                    "type": "PolicyDeniedError",
                    "message": "policy says no",
                },
            },
        )

    @patch.object(
        main,
        "start_workflow",
        side_effect=BudgetExceededError(
            "budget says stop",
            budget_name="max_tool_calls",
        ),
    )
    def test_run_budget_exhausted_returns_429(self, _mock_start_workflow) -> None:
        response = main.run({"agent": "default"})

        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            json.loads(response.body),
            {
                "status": "error",
                "error": {
                    "type": "BudgetExceededError",
                    "message": "budget says stop",
                },
            },
        )

    @patch.object(main, "start_workflow")
    def test_run_passes_approval_id(self, mock_start_workflow) -> None:
        mock_start_workflow.return_value = {"status": "pending"}

        response = main.run({"agent": "default", "approval_id": "approval-123"})

        self.assertEqual(response["status"], "pending")
        mock_start_workflow.assert_called_once_with(
            user_input="",
            agent_name="default",
            tool_name=None,
            tool_args=None,
            approval_id="approval-123",
        )

    @patch.object(main, "start_workflow")
    def test_workflow_start_passthrough(self, mock_start_workflow) -> None:
        mock_start_workflow.return_value = {"status": "success", "workflow": {"workflow_id": "wf-123"}}

        response = main.workflow_start({"agent": "default", "tool": "echo", "tool_args": {"text": "hello"}})

        self.assertEqual(response["status"], "success")
        mock_start_workflow.assert_called_once_with(
            user_input="",
            agent_name="default",
            tool_name="echo",
            tool_args={"text": "hello"},
            approval_id=None,
        )

    @patch.object(
        main,
        "get_approval",
        return_value={"approval_id": "approval-123", "status": "pending"},
    )
    def test_approval_status_passthrough(self, _mock_get_approval) -> None:
        response = main.approval_status("approval-123")

        self.assertEqual(response["approval_id"], "approval-123")
        self.assertEqual(response["status"], "pending")

    @patch.object(
        main,
        "load_artifact",
        return_value={"artifact_id": "artifact-123", "kind": "tool_output"},
    )
    def test_artifact_status_passthrough(self, _mock_load_artifact) -> None:
        response = main.artifact_status("artifact-123")

        self.assertEqual(response["artifact_id"], "artifact-123")
        self.assertEqual(response["kind"], "tool_output")

    @patch.object(main, "list_memories", return_value=[{"memory_id": "memory-123"}])
    def test_memory_list_passthrough(self, mock_list_memories) -> None:
        response = main.memory_list(
            memory_type="fact",
            scope_kind="agent",
            agent="researcher",
            workflow_id="wf-123",
            run_id="run-123",
            tags="runtime,retry",
            limit=5,
        )

        self.assertEqual(response["memories"], [{"memory_id": "memory-123"}])
        mock_list_memories.assert_called_once_with(
            memory_type="fact",
            scope_kind="agent",
            agent="researcher",
            workflow_id="wf-123",
            run_id="run-123",
            tags=["runtime", "retry"],
            limit=5,
        )

    @patch.object(main, "load_memory", return_value={"memory_id": "memory-123", "memory_type": "fact"})
    def test_memory_status_passthrough(self, _mock_load_memory) -> None:
        response = main.memory_status("memory-123")

        self.assertEqual(response["memory_id"], "memory-123")
        self.assertEqual(response["memory_type"], "fact")

    @patch.object(main, "delete_memory", return_value={"memory_id": "memory-123", "memory_type": "fact"})
    def test_memory_delete_passthrough(self, _mock_delete_memory) -> None:
        response = main.memory_delete("memory-123")

        self.assertEqual(response["memory_id"], "memory-123")
        self.assertEqual(response["memory_type"], "fact")

    @patch.object(
        main,
        "approve_approval",
        return_value={"approval_id": "approval-123", "status": "approved"},
    )
    def test_approval_approve_passthrough(self, _mock_approve_approval) -> None:
        response = main.approval_approve("approval-123")

        self.assertEqual(response["approval_id"], "approval-123")
        self.assertEqual(response["status"], "approved")

    @patch.object(
        main,
        "workflow_control_view",
        return_value={"workflow_id": "workflow-123", "status": "waiting", "actions": {}},
    )
    def test_workflow_status_passthrough(self, _mock_workflow_control_view) -> None:
        response = main.workflow_status("workflow-123")

        self.assertEqual(response["workflow_id"], "workflow-123")
        self.assertEqual(response["status"], "waiting")

    @patch.object(main, "resume_workflow", return_value={"status": "success"})
    def test_workflow_resume_passthrough(self, mock_resume_workflow) -> None:
        response = main.workflow_resume("workflow-123")

        self.assertEqual(response["status"], "success")
        mock_resume_workflow.assert_called_once_with("workflow-123")

    @patch.object(main, "start_child_workflow", return_value={"status": "success"})
    def test_workflow_spawn_subrun_passthrough(self, mock_start_child_workflow) -> None:
        response = main.workflow_spawn_subrun(
            "workflow-123",
            {"agent": "researcher", "tool": "echo", "tool_args": {"text": "hello"}},
        )

        self.assertEqual(response["status"], "success")
        mock_start_child_workflow.assert_called_once_with(
            "workflow-123",
            user_input="",
            agent_name="researcher",
            tool_name="echo",
            tool_args={"text": "hello"},
        )

    @patch.object(
        main,
        "abort_approval",
        side_effect=ApprovalStateError(
            "cannot abort",
            approval_id="approval-123",
        ),
    )
    def test_approval_abort_state_error_returns_409(self, _mock_abort_approval) -> None:
        response = main.approval_abort("approval-123")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.body),
            {
                "status": "error",
                "error": {
                    "type": "ApprovalStateError",
                    "message": "cannot abort",
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
