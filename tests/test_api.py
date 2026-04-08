import json
import unittest
from pathlib import Path
from unittest.mock import patch

import api.main as main
from runtime.errors import ApprovalStateError, BudgetExceededError, DelegationDeniedError, PolicyDeniedError
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


class ApiTests(unittest.TestCase):
    def test_operator_auth_status_reports_disabled_by_default(self) -> None:
        with patch.dict(main.os.environ, {}, clear=True):
            response = main.operator_auth()

        self.assertEqual(
            response,
            {
                "enabled": False,
                "header": "X-Operator-Token",
                "env_var": "CLARITYOS_OPERATOR_TOKEN",
            },
        )

    @patch.object(main, "models_config_path", return_value=Path("/tmp/models.production.yaml"))
    @patch.object(main, "policies_config_path", return_value=Path("/tmp/policies.production.yaml"))
    @patch.object(main, "agents_config_path", return_value=Path("/tmp/agents.production.yaml"))
    def test_operator_profile_reports_runtime_posture(
        self,
        _mock_agents_config_path,
        _mock_policies_config_path,
        _mock_models_config_path,
    ) -> None:
        with patch.dict(
            main.os.environ,
            {
                "CLARITYOS_ENV": "production",
                "CLARITYOS_ALLOW_AGENT_POLICY_OVERRIDES": "1",
            },
            clear=True,
        ):
            response = main.operator_profile_status()

        self.assertEqual(response["environment"]["name"], "production")
        self.assertTrue(response["environment"]["production_mode"])
        self.assertTrue(response["policy"]["allow_agent_overrides"])
        self.assertEqual(response["config"]["agents"]["path"], "/tmp/agents.production.yaml")
        self.assertEqual(response["config"]["policies"]["env_var"], "CLARITYOS_POLICIES_CONFIG")
        self.assertEqual(response["state"]["current_version"], "v0.9")

    @patch.object(main, "operator_dashboard_view", return_value={"session_rollup": {"total_sessions": 2}})
    def test_operator_dashboard_passthrough(self, mock_operator_dashboard_view) -> None:
        response = main.operator_dashboard(session_limit=5)

        self.assertEqual(response["session_rollup"]["total_sessions"], 2)
        mock_operator_dashboard_view.assert_called_once_with(session_limit=5)

    @patch.object(main, "queue_health_view", return_value={"health": {"retry_backlog_count": 1}})
    def test_operator_endpoint_requires_token_when_configured(self, _mock_queue_health_view) -> None:
        with patch.dict(main.os.environ, {"CLARITYOS_OPERATOR_TOKEN": "secret-token"}, clear=True):
            response = main.queue_health()

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            json.loads(response.body),
            {
                "status": "error",
                "error": {
                    "type": "OperatorAuthError",
                    "message": "Operator token is required via `X-Operator-Token`",
                },
            },
        )

    @patch.object(main, "queue_health_view", return_value={"health": {"retry_backlog_count": 1}})
    def test_operator_endpoint_accepts_valid_token_when_configured(self, mock_queue_health_view) -> None:
        with patch.dict(main.os.environ, {"CLARITYOS_OPERATOR_TOKEN": "secret-token"}, clear=True):
            response = main.queue_health(x_operator_token="secret-token")

        self.assertEqual(response["health"]["retry_backlog_count"], 1)
        mock_queue_health_view.assert_called_once_with()

    @patch.object(main, "register_worker", return_value={"worker_id": "worker-123", "status": "idle"})
    def test_worker_create_passthrough(self, mock_register_worker) -> None:
        response = main.worker_create({"name": "queue-1", "lease_seconds": 45})

        self.assertEqual(response["worker_id"], "worker-123")
        mock_register_worker.assert_called_once_with(name="queue-1", lease_seconds=45)

    @patch.object(main, "create_session", return_value={"session_id": "session-123", "status": "open"})
    def test_session_create_passthrough(self, mock_create_session) -> None:
        response = main.session_create({"title": "Inbox", "agent": "default"})

        self.assertEqual(response["session_id"], "session-123")
        mock_create_session.assert_called_once_with(
            title="Inbox",
            agent="default",
            metadata=None,
            memory_scope=None,
        )

    @patch.object(main, "assistant_html", return_value="<html><body>assistant-surface</body></html>")
    def test_assistant_surface_returns_html(self, mock_assistant_html) -> None:
        response = main.assistant_surface()

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"assistant-surface", response.body)
        mock_assistant_html.assert_called_once_with()

    @patch.object(main, "operator_html", return_value="<html><body>operator-console</body></html>")
    def test_operator_surface_returns_html(self, mock_operator_html) -> None:
        response = main.operator_surface()

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"operator-console", response.body)
        mock_operator_html.assert_called_once_with()

    @patch.object(main, "widget_html", return_value="<html><body>widget-surface</body></html>")
    def test_widget_surface_returns_html(self, mock_widget_html) -> None:
        response = main.widget_surface(request_for("/widget"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"widget-surface", response.body)
        mock_widget_html.assert_called_once_with()

    def test_widget_surface_rejects_disallowed_parent_origin(self) -> None:
        with patch.dict(main.os.environ, {}, clear=True):
            response = main.widget_surface(
                request_for("/widget", query_string=b"parent_origin=https%3A%2F%2Fexample.com"),
                parent_origin="https://example.com",
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"Widget Origin Not Allowed", response.body)

    @patch.object(main, "widget_script", return_value="console.log('widget-loader');")
    def test_widget_loader_returns_javascript(self, mock_widget_script) -> None:
        response = main.widget_loader(request_for("/widget.js"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"widget-loader", response.body)
        self.assertIn(b"__CLARITYOS_WIDGET_CONFIG__", response.body)
        self.assertEqual(response.media_type, "application/javascript")
        mock_widget_script.assert_called_once_with()

    def test_widget_config_reports_requested_origin_allowed(self) -> None:
        with patch.dict(
            main.os.environ,
            {
                "CLARITYOS_WIDGET_ALLOWED_ORIGINS": "https://app.example.com,https://admin.example.com",
                "CLARITYOS_WIDGET_BRAND_NAME": "Site Assistant",
            },
            clear=True,
        ):
            response = main.widget_config(
                request_for("/widget/config", query_string=b"origin=https%3A%2F%2Fapp.example.com"),
                origin="https://app.example.com",
            )

        self.assertEqual(response["requested_origin"], "https://app.example.com")
        self.assertTrue(response["requested_origin_allowed"])
        self.assertEqual(response["branding"]["name"], "Site Assistant")
        self.assertEqual(
            response["allowed_origins"],
            ["https://app.example.com", "https://admin.example.com"],
        )

    @patch.object(main, "list_sessions", return_value=[{"session_id": "session-123"}])
    def test_session_list_passthrough(self, mock_list_sessions) -> None:
        response = main.session_list(status="open", agent="default", limit=5)

        self.assertEqual(response["sessions"], [{"session_id": "session-123"}])
        mock_list_sessions.assert_called_once_with(status="open", agent="default", limit=5)

    @patch.object(main, "session_snapshot", return_value={"session_id": "session-123", "status": "active"})
    @patch.object(main, "load_session", return_value=object())
    def test_session_status_passthrough(self, mock_load_session, mock_session_snapshot) -> None:
        response = main.session_status("session-123")

        self.assertEqual(response["session_id"], "session-123")
        mock_load_session.assert_called_once_with("session-123")
        mock_session_snapshot.assert_called_once()

    @patch.object(main, "session_snapshot", return_value={"session_id": "session-123", "status": "active"})
    @patch.object(main, "load_session", return_value=object())
    def test_assistant_session_status_passthrough(self, mock_load_session, mock_session_snapshot) -> None:
        response = main.assistant_session_status("session-123")

        self.assertEqual(response["session_id"], "session-123")
        mock_load_session.assert_called_once_with("session-123")
        mock_session_snapshot.assert_called_once()

    @patch.object(main, "session_control_view", return_value={"session_id": "session-123", "workflow_rollup": {}})
    def test_session_control_passthrough(self, mock_session_control_view) -> None:
        response = main.session_control("session-123")

        self.assertEqual(response["session_id"], "session-123")
        mock_session_control_view.assert_called_once_with("session-123")

    @patch.object(
        main,
        "append_message_to_session",
        return_value={"session": {"session_id": "session-123"}, "workflow_result": {"status": "success"}},
    )
    def test_session_append_message_passthrough(self, mock_append_session_message) -> None:
        response = main.session_append_message(
            "session-123",
            {"input": "hello", "agent": "default"},
        )

        self.assertEqual(response["session"]["session_id"], "session-123")
        mock_append_session_message.assert_called_once_with(
            "session-123",
            content="hello",
            agent="default",
            tool_name=None,
            tool_args=None,
            approval_id=None,
            metadata=None,
        )

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

    @patch.object(main, "repair_orphaned_workers", return_value={"repaired_count": 2})
    def test_worker_repair_orphans_passthrough(self, mock_repair_orphaned_workers) -> None:
        response = main.worker_repair_orphans({"limit": 5})

        self.assertEqual(response["repaired_count"], 2)
        mock_repair_orphaned_workers.assert_called_once_with(limit=5)

    @patch.object(main, "reset_worker", return_value={"worker": {"worker_id": "worker-123", "status": "idle"}})
    def test_worker_reset_passthrough(self, mock_reset_worker) -> None:
        response = main.worker_reset(
            "worker-123",
            {"reason": "operator reset", "force": True, "requeue_running_job": False},
        )

        self.assertEqual(response["worker"]["worker_id"], "worker-123")
        mock_reset_worker.assert_called_once_with(
            "worker-123",
            reason="operator reset",
            force=True,
            requeue_running_job=False,
        )

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

    @patch.object(main, "create_job", return_value={"job_id": "job-123", "status": "queued"})
    def test_job_create_workflow_subrun_includes_delegation_fields(self, mock_create_job) -> None:
        response = main.job_create(
            {
                "type": "workflow_subrun",
                "workflow_id": "wf-parent",
                "agent": "researcher",
                "role": "summarizer",
                "allowed_capabilities": ["model_call"],
                "shared_memory_ids": ["memory-123"],
            }
        )

        self.assertEqual(response["job_id"], "job-123")
        mock_create_job.assert_called_once_with(
            job_type="workflow_subrun",
            payload={
                "input": "",
                "agent": "researcher",
                "tool": None,
                "tool_args": None,
                "approval_id": None,
                "workflow_id": "wf-parent",
                "role": "summarizer",
                "allowed_capabilities": ["model_call"],
                "allowed_tools": None,
                "shared_memory_ids": ["memory-123"],
            },
            priority=100,
            delay_seconds=0,
            run_at=None,
            workflow_id="wf-parent",
            parent_job_id=None,
            idempotency_key=None,
            max_attempts=1,
            retry_backoff_seconds=30,
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

    @patch.object(main, "queue_health_view", return_value={"health": {"retry_backlog_count": 1}})
    def test_queue_health_passthrough(self, mock_queue_health_view) -> None:
        response = main.queue_health()

        self.assertEqual(response["health"]["retry_backlog_count"], 1)
        mock_queue_health_view.assert_called_once_with()

    @patch.object(main, "promote_due_jobs", return_value={"promoted_count": 1, "promoted_job_ids": ["job-123"]})
    def test_queue_promote_ready_passthrough(self, mock_promote_due_jobs) -> None:
        response = main.queue_promote_ready({"limit": 5})

        self.assertEqual(response["promoted_count"], 1)
        mock_promote_due_jobs.assert_called_once_with(limit=5)

    @patch.object(main, "repair_stale_job_state", return_value={"repaired_count": 2})
    def test_queue_repair_stale_passthrough(self, mock_repair_stale_job_state) -> None:
        response = main.queue_repair_stale({"limit": 10})

        self.assertEqual(response["repaired_count"], 2)
        mock_repair_stale_job_state.assert_called_once_with(limit=10)

    @patch.object(main, "prune_jobs", return_value={"pruned_count": 1, "pruned_job_ids": ["job-123"]})
    def test_queue_prune_passthrough(self, mock_prune_jobs) -> None:
        response = main.queue_prune(
            {"statuses": ["dead_letter"], "older_than_seconds": 3600, "limit": 5}
        )

        self.assertEqual(response["pruned_count"], 1)
        mock_prune_jobs.assert_called_once_with(
            statuses=["dead_letter"],
            older_than_seconds=3600,
            limit=5,
        )

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

    def test_state_schemas_returns_current_version_and_catalog(self) -> None:
        response = main.state_schemas()

        self.assertEqual(response["current_version"], "v0.9")
        self.assertEqual(response["schemas"]["sessions"]["schema"], "session.v1")
        self.assertEqual(response["schemas"]["workflows"]["schema"], "workflow.v1")
        self.assertEqual(response["schemas"]["jobs"]["schema"], "job.v1")

    @patch.object(
        main,
        "inspect_state_payload",
        return_value={
            "schema": "workflow.v1",
            "expected_schema": "workflow.v1",
            "version": "v0.9",
            "current_version": "v0.9",
            "legacy_format": False,
            "supported": True,
            "payload_keys": ["workflow_id"],
        },
    )
    @patch.object(main, "workflow_path")
    def test_state_inspect_passthrough(self, mock_workflow_path, mock_inspect_state_payload) -> None:
        mock_workflow_path.return_value = type(
            "FakePath",
            (),
            {"is_file": lambda self: True},
        )()

        response = main.state_inspect("workflows", "wf-123", include_payload=True)

        self.assertEqual(response["kind"], "workflows")
        self.assertEqual(response["state_id"], "wf-123")
        self.assertEqual(response["schema"], "workflow.v1")
        mock_inspect_state_payload.assert_called_once()

    def test_state_inspect_rejects_unknown_kind(self) -> None:
        response = main.state_inspect("bogus", "id-123")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.body),
            {
                "status": "error",
                "error": {
                    "type": "ValueError",
                    "message": "State `kind` must be one of: sessions, workflows, jobs, memories, workers, approvals, artifacts",
                },
            },
        )

    @patch.object(
        main,
        "migrate_state_payload",
        return_value={
            "migrated": True,
            "before": {"legacy_format": True},
            "after": {"legacy_format": False, "schema": "workflow.v1", "version": "v0.9"},
        },
    )
    @patch.object(main, "workflow_path")
    def test_state_migrate_passthrough(self, mock_workflow_path, mock_migrate_state_payload) -> None:
        mock_workflow_path.return_value = type(
            "FakePath",
            (),
            {"is_file": lambda self: True},
        )()

        response = main.state_migrate("workflows", "wf-123")

        self.assertEqual(response["kind"], "workflows")
        self.assertEqual(response["state_id"], "wf-123")
        self.assertTrue(response["migrated"])
        mock_migrate_state_payload.assert_called_once()

    @patch.object(
        main,
        "migrate_state_directory",
        return_value={"processed_count": 2, "migrated_count": 1, "unchanged_count": 1, "results": []},
    )
    def test_state_migrate_all_passthrough(self, mock_migrate_state_directory) -> None:
        response = main.state_migrate_all("workflows", {"limit": 5, "include_unchanged": True})

        self.assertEqual(response["kind"], "workflows")
        self.assertEqual(response["processed_count"], 2)
        mock_migrate_state_directory.assert_called_once()

    @patch.object(
        main,
        "migrate_state_directory",
        side_effect=[
            {"processed_count": 2, "migrated_count": 1, "unchanged_count": 1, "results": []},
            {"processed_count": 1, "migrated_count": 1, "unchanged_count": 0, "results": []},
        ],
    )
    def test_state_migrate_runtime_passthrough(self, mock_migrate_state_directory) -> None:
        response = main.state_migrate_runtime({"kinds": ["workflows", "jobs"], "limit_per_kind": 10})

        self.assertEqual(response["kinds"], ["workflows", "jobs"])
        self.assertEqual(response["processed_count"], 3)
        self.assertEqual(response["migrated_count"], 2)
        self.assertEqual(response["unchanged_count"], 1)
        self.assertEqual(mock_migrate_state_directory.call_count, 2)

    def test_state_migrate_runtime_rejects_empty_kinds(self) -> None:
        response = main.state_migrate_runtime({"kinds": []})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.body),
            {
                "status": "error",
                "error": {
                    "type": "ValueError",
                    "message": "State migration `kinds` must be a non-empty list",
                },
            },
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

    @patch.object(
        main,
        "workflow_incident_view",
        return_value={"workflow_id": "workflow-123", "incident": {"trace_count": 2}},
    )
    def test_workflow_incident_passthrough(self, mock_workflow_incident_view) -> None:
        response = main.workflow_incident("workflow-123", trace_limit=5)

        self.assertEqual(response["workflow_id"], "workflow-123")
        self.assertEqual(response["incident"]["trace_count"], 2)
        mock_workflow_incident_view.assert_called_once_with("workflow-123", trace_limit=5)

    @patch.object(
        main,
        "workflow_incident_summary_view",
        return_value={"workflow_id": "workflow-123", "incident": {"rollup": {"current_blocker": {"kind": "runtime_error"}}}},
    )
    def test_workflow_incident_summary_passthrough(self, mock_workflow_incident_summary_view) -> None:
        response = main.workflow_incident_summary("workflow-123", trace_limit=5)

        self.assertEqual(response["workflow_id"], "workflow-123")
        self.assertEqual(response["incident"]["rollup"]["current_blocker"]["kind"], "runtime_error")
        mock_workflow_incident_summary_view.assert_called_once_with("workflow-123", trace_limit=5)

    @patch.object(main, "recover_workflow", return_value={"workflow_id": "workflow-123", "reclaimed_count": 1})
    def test_workflow_recover_passthrough(self, mock_recover_workflow) -> None:
        response = main.workflow_recover(
            "workflow-123",
            {
                "reclaim_expired_jobs": True,
                "reschedule_failed_jobs": True,
                "reschedule_dead_letter_jobs": False,
                "limit": 5,
            },
        )

        self.assertEqual(response["workflow_id"], "workflow-123")
        self.assertEqual(response["reclaimed_count"], 1)
        mock_recover_workflow.assert_called_once_with(
            "workflow-123",
            reclaim_expired_jobs=True,
            reschedule_failed_jobs=True,
            reschedule_dead_letter_jobs=False,
            limit=5,
        )

    @patch.object(main, "resume_workflow", return_value={"status": "success"})
    def test_workflow_resume_passthrough(self, mock_resume_workflow) -> None:
        response = main.workflow_resume("workflow-123")

        self.assertEqual(response["status"], "success")
        mock_resume_workflow.assert_called_once_with("workflow-123")

    @patch.object(main, "safe_resume_workflow", return_value={"status": "success"})
    def test_workflow_resume_safe_passthrough(self, mock_safe_resume_workflow) -> None:
        response = main.workflow_resume_safe("workflow-123")

        self.assertEqual(response["status"], "success")
        mock_safe_resume_workflow.assert_called_once_with("workflow-123")

    @patch.object(main, "worker_health_view", return_value={"counts": {"idle": 1}})
    def test_workers_health_passthrough(self, mock_worker_health_view) -> None:
        response = main.workers_health()

        self.assertEqual(response["counts"]["idle"], 1)
        mock_worker_health_view.assert_called_once_with()

    @patch.object(
        main,
        "replay_workflow",
        return_value={"replayed_from_workflow_id": "workflow-123", "result": {"status": "success"}},
    )
    def test_workflow_replay_passthrough(self, mock_replay_workflow) -> None:
        response = main.workflow_replay("workflow-123")

        self.assertEqual(response["replayed_from_workflow_id"], "workflow-123")
        mock_replay_workflow.assert_called_once_with("workflow-123")

    @patch.object(main, "start_child_workflow", return_value={"status": "success"})
    def test_workflow_spawn_subrun_passthrough(self, mock_start_child_workflow) -> None:
        response = main.workflow_spawn_subrun(
            "workflow-123",
            {
                "agent": "researcher",
                "tool": "echo",
                "tool_args": {"text": "hello"},
                "role": "summarizer",
                "allowed_capabilities": ["exec"],
                "allowed_tools": ["echo"],
                "shared_memory_ids": ["memory-123"],
            },
        )

        self.assertEqual(response["status"], "success")
        mock_start_child_workflow.assert_called_once_with(
            "workflow-123",
            user_input="",
            agent_name="researcher",
            tool_name="echo",
            tool_args={"text": "hello"},
            role="summarizer",
            allowed_capabilities=["exec"],
            allowed_tools=["echo"],
            shared_memory_ids=["memory-123"],
        )

    @patch.object(
        main,
        "start_child_workflow",
        side_effect=DelegationDeniedError(
            "delegation says no",
            capability="model_call",
            workflow_id="wf-parent",
        ),
    )
    def test_workflow_spawn_subrun_delegation_error_returns_403(self, _mock_start_child_workflow) -> None:
        response = main.workflow_spawn_subrun("workflow-123", {"agent": "researcher"})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            json.loads(response.body),
            {
                "status": "error",
                "error": {
                    "type": "DelegationDeniedError",
                    "message": "delegation says no",
                },
            },
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
