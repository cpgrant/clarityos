import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import api.main as main
import runtime.approval as approval_runtime
import runtime.artifact as artifact_runtime
import runtime.memory as memory_runtime
import runtime.queue as queue_runtime
import runtime.session as session_runtime
import runtime.trace as trace_runtime
import runtime.worker as worker_runtime
import runtime.workflow as workflow_runtime
from starlette.requests import Request


def request_for(path: str, query_string: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("127.0.0.1", 8000),
            "method": "GET",
            "path": path,
            "query_string": query_string,
            "headers": [],
        }
    )


class BrowserSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.stack = ExitStack()

        self.session_dir = self.root_dir / "sessions"
        self.workflow_dir = self.root_dir / "workflows"
        self.artifact_dir = self.root_dir / "artifacts"
        self.log_dir = self.root_dir / "logs"
        self.approval_dir = self.root_dir / "approvals"
        self.job_dir = self.root_dir / "jobs"
        self.worker_dir = self.root_dir / "workers"
        self.memory_dir = self.root_dir / "memories"

        for directory in (
            self.session_dir,
            self.workflow_dir,
            self.artifact_dir,
            self.log_dir,
            self.approval_dir,
            self.job_dir,
            self.worker_dir,
            self.memory_dir,
        ):
            directory.mkdir()

        self.stack.enter_context(patch.object(session_runtime, "SESSION_DIR", self.session_dir))
        self.stack.enter_context(patch.object(workflow_runtime, "WORKFLOW_DIR", self.workflow_dir))
        self.stack.enter_context(patch.object(artifact_runtime, "ARTIFACT_DIR", self.artifact_dir))
        self.stack.enter_context(patch.object(trace_runtime, "LOG_DIR", self.log_dir))
        self.stack.enter_context(patch.object(approval_runtime, "APPROVAL_DIR", self.approval_dir))
        self.stack.enter_context(patch.object(queue_runtime, "JOB_DIR", self.job_dir))
        self.stack.enter_context(patch.object(worker_runtime, "WORKER_DIR", self.worker_dir))
        self.stack.enter_context(patch.object(memory_runtime, "MEMORY_DIR", self.memory_dir))
        self.stack.enter_context(
            patch(
                "runtime.agent.call_model",
                side_effect=self.fake_call_model,
            )
        )

    def tearDown(self) -> None:
        self.stack.close()
        self.temp_dir.cleanup()

    @staticmethod
    def fake_call_model(model_name: str, prompt: str) -> dict:
        if "PROJECT CONTEXT" in prompt:
            output = "Grounded smoke response"
        else:
            output = "Smoke response"
        return {
            "provider": "stub",
            "model": model_name,
            "output": output,
        }

    @staticmethod
    def response_text(response) -> str:
        return response.body.decode("utf-8")

    def create_browser_session(self, *, surface: str, agent: str = "default") -> tuple[str, str]:
        response = main.session_create(
            {
                "title": "Smoke Session",
                "agent": agent,
                "surface": surface,
            }
        )
        return response["session_id"], response["session_token"]

    def test_assistant_surface_smoke_round_trip(self) -> None:
        response = main.assistant_surface()

        self.assertEqual(response.status_code, 200)
        body = self.response_text(response)
        self.assertIn("Browser-First Assistant", body)
        self.assertIn('id="message-input"', body)
        self.assertIn('id="send-button"', body)

        session_id, session_token = self.create_browser_session(surface="assistant_web")

        append_response = main.session_append_message(
            session_id,
            {"input": "Hello from the browser smoke test."},
            x_session_token=session_token,
            x_operator_token=None,
        )

        self.assertEqual(append_response["session"]["status"], "active")
        self.assertEqual(append_response["workflow_result"]["status"], "success")

        status_response = main.assistant_session_status(
            session_id,
            x_session_token=session_token,
            x_operator_token=None,
        )

        self.assertEqual(status_response["session_id"], session_id)
        self.assertEqual(status_response["message_count"], 2)
        self.assertEqual(status_response["messages"][0]["role"], "user")
        self.assertEqual(status_response["messages"][1]["role"], "assistant")
        self.assertEqual(status_response["messages"][1]["content"], "Smoke response")
        self.assertIsNotNone(status_response["current_workflow_id"])

    def test_operator_surface_smoke_dashboard_and_session_control(self) -> None:
        session_id, session_token = self.create_browser_session(surface="assistant_web")
        main.session_append_message(
            session_id,
            {"input": "Summarize the current release state."},
            x_session_token=session_token,
            x_operator_token=None,
        )

        with patch.dict(main.os.environ, {"CLARITYCLAW_OPERATOR_TOKEN": "secret-token"}, clear=False):
            html_response = main.operator_surface()
            self.assertEqual(html_response.status_code, 200)
            body = self.response_text(html_response)
            self.assertIn("ClarityClaw v1.7", body)
            self.assertIn("Operator Console", body)
            self.assertIn("Runtime Posture", body)
            self.assertIn("Email Triage", body)
            self.assertIn("session-item", body)

            dashboard_response = main.operator_dashboard(
                x_operator_token="secret-token",
            )
            self.assertEqual(dashboard_response["session_rollup"]["total_sessions"], 1)
            self.assertEqual(dashboard_response["sessions"][0]["session_id"], session_id)

            control_response = main.session_control(
                session_id,
                x_operator_token="secret-token",
            )
            self.assertEqual(control_response["session_id"], session_id)
            self.assertEqual(control_response["session_rollup"]["message_count"], 2)
            self.assertEqual(control_response["workflow_rollup"]["counts"]["succeeded"], 1)
            self.assertEqual(control_response["current_workflow"]["status"], "succeeded")

    def test_widget_surface_smoke_loader_config_and_session_flow(self) -> None:
        with patch.dict(
            main.os.environ,
            {
                "CLARITYCLAW_WIDGET_ALLOWED_ORIGINS": "http://testserver",
                "CLARITYCLAW_WIDGET_ALLOWED_AGENTS": "default,researcher",
                "CLARITYCLAW_WIDGET_BRAND_NAME": "Smoke Widget",
                "CLARITYCLAW_WIDGET_LAUNCHER_LABEL": "Ask Smoke",
            },
            clear=False,
        ):
            frame_response = main.widget_surface(
                request_for("/widget"),
                parent_origin="http://testserver",
            )
            self.assertEqual(frame_response.status_code, 200)
            body = self.response_text(frame_response)
            self.assertIn("Smoke Widget", body)
            self.assertIn('id="message-input"', body)

            loader_response = main.widget_loader(request_for("/widget.js"))
            self.assertEqual(loader_response.status_code, 200)
            loader_body = loader_response.body.decode("utf-8")
            self.assertIn("__CLARITYCLAW_WIDGET_CONFIG__", loader_body)
            self.assertIn("Ask Smoke", loader_body)
            self.assertIn("/widget?title=", loader_body)

            config_response = main.widget_config(
                request_for("/widget/config", query_string=b"origin=http%3A%2F%2Ftestserver"),
                origin="http://testserver",
            )
            self.assertTrue(config_response["requested_origin_allowed"])
            self.assertEqual(config_response["branding"]["name"], "Smoke Widget")
            self.assertEqual(sorted(config_response["allowed_agents"]), ["default", "researcher"])

        session_id, session_token = self.create_browser_session(surface="embed_widget", agent="default")
        append_response = main.session_append_message(
            session_id,
            {"input": "Widget smoke thread."},
            x_session_token=session_token,
            x_operator_token=None,
        )
        self.assertEqual(append_response["session"]["status"], "active")

        status_response = main.assistant_session_status(
            session_id,
            x_session_token=session_token,
            x_operator_token=None,
        )
        self.assertEqual(status_response["ownership"]["surface"], "embed_widget")
        self.assertEqual(status_response["message_count"], 2)


if __name__ == "__main__":
    unittest.main()
