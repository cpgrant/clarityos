import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime.agent as agent
import runtime.trace as trace


def fake_model(model_name: str, prompt: str) -> dict:
    return {
        "provider": "test",
        "model": "fake-model",
        "output": "ok",
    }


class RunAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.temp_dir.name)
        self.trace_patcher = patch.object(trace, "LOG_DIR", self.log_dir)
        self.trace_patcher.start()

    def tearDown(self) -> None:
        self.trace_patcher.stop()
        self.temp_dir.cleanup()

    def latest_log(self) -> dict:
        log_files = sorted(self.log_dir.glob("run_*.json"))
        self.assertTrue(log_files, "Expected at least one trace log")

        with log_files[-1].open(encoding="utf-8") as file:
            return json.load(file)

    @patch.object(agent, "call_model", side_effect=fake_model)
    def test_run_agent_success(self, _mock_call_model) -> None:
        result = agent.run_agent("hello", "default")

        self.assertEqual(result["agent"], "default")
        self.assertEqual(result["provider"], "test")
        self.assertEqual(result["model"], "fake-model")
        self.assertEqual(result["output"], "ok")

    @patch.object(agent, "call_model", side_effect=fake_model)
    def test_trace_created_for_success(self, _mock_call_model) -> None:
        agent.run_agent("hello", "default")

        payload = self.latest_log()

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["version"], "v0.2")
        self.assertEqual(payload["input"], "hello")
        self.assertEqual(payload["agent"], "default")
        self.assertEqual(payload["model_alias"], "fast")
        self.assertEqual(payload["provider"], "test")
        self.assertEqual(payload["model"], "fake-model")
        self.assertEqual(payload["output"], "ok")
        self.assertIn("run_id", payload)
        self.assertIn("duration_ms", payload)
        self.assertIn("timestamp", payload)

    def test_run_agent_missing_logs_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown agent: missing"):
            agent.run_agent("hello", "missing")

        payload = self.latest_log()

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["version"], "v0.2")
        self.assertEqual(payload["input"], "hello")
        self.assertEqual(payload["agent"], "missing")
        self.assertIsNone(payload["prompt"])
        self.assertIsNone(payload["model_alias"])
        self.assertEqual(payload["error_type"], "ValueError")
        self.assertIn("Unknown agent: missing", payload["error_message"])
        self.assertIn("run_id", payload)
        self.assertIn("duration_ms", payload)
        self.assertIn("timestamp", payload)


if __name__ == "__main__":
    unittest.main()
