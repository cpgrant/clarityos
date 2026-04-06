import json
import unittest
from unittest.mock import patch

import api.main as main
from runtime.errors import ApprovalStateError, BudgetExceededError, PolicyDeniedError


class ApiTests(unittest.TestCase):
    @patch.object(main, "run_agent")
    def test_run_success_passthrough(self, mock_run_agent) -> None:
        mock_run_agent.return_value = {
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

    @patch.object(main, "run_agent", side_effect=ValueError("bad input"))
    def test_run_value_error_returns_400(self, _mock_run_agent) -> None:
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

    @patch.object(main, "run_agent", side_effect=FileNotFoundError("missing file"))
    def test_run_missing_file_returns_404(self, _mock_run_agent) -> None:
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

    @patch.object(main, "run_agent", side_effect=RuntimeError("boom"))
    def test_run_runtime_error_returns_500(self, _mock_run_agent) -> None:
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
        "run_agent",
        side_effect=PolicyDeniedError(
            "policy says no",
            capability="model_call",
            policy_name="safe_readonly",
        ),
    )
    def test_run_policy_denied_returns_403(self, _mock_run_agent) -> None:
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
        "run_agent",
        side_effect=BudgetExceededError(
            "budget says stop",
            budget_name="max_tool_calls",
        ),
    )
    def test_run_budget_exhausted_returns_429(self, _mock_run_agent) -> None:
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

    @patch.object(main, "run_agent")
    def test_run_passes_approval_id(self, mock_run_agent) -> None:
        mock_run_agent.return_value = {"status": "pending"}

        response = main.run({"agent": "default", "approval_id": "approval-123"})

        self.assertEqual(response["status"], "pending")
        mock_run_agent.assert_called_once_with(
            user_input="",
            agent_name="default",
            tool_name=None,
            tool_args=None,
            approval_id="approval-123",
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
        "approve_approval",
        return_value={"approval_id": "approval-123", "status": "approved"},
    )
    def test_approval_approve_passthrough(self, _mock_approve_approval) -> None:
        response = main.approval_approve("approval-123")

        self.assertEqual(response["approval_id"], "approval-123")
        self.assertEqual(response["status"], "approved")

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
