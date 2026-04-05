import json
import unittest
from unittest.mock import patch

import api.main as main


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


if __name__ == "__main__":
    unittest.main()
