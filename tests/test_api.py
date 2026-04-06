import json
import unittest
from unittest.mock import patch

import api.main as main
from runtime.errors import ApprovalStateError, BudgetExceededError, PolicyDeniedError


class ApiTests(unittest.TestCase):
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
