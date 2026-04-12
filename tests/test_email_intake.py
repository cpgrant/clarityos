import unittest
from unittest.mock import patch

from runtime.email_intake import (
    build_email_draft_handoff_value,
    build_email_triage_artifact_value,
    build_email_triage_prompt,
    create_email_draft_handoff,
    find_email_draft_approval,
    find_email_draft_handoff,
    intake_email,
    normalize_email_payload,
    parse_email_triage_output,
    persist_email_triage_artifact,
    request_email_draft_approval,
)


class EmailIntakeTests(unittest.TestCase):
    def test_normalize_email_payload_requires_body_or_snippet(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires either `text_body` or `snippet`"):
            normalize_email_payload(
                {
                    "account": "ops@example.com",
                    "message_id": "msg-123",
                }
            )

    def test_normalize_email_payload_normalizes_lists_and_defaults_subject(self) -> None:
        normalized = normalize_email_payload(
            {
                "account": "ops@example.com",
                "message_id": "msg-123",
                "to": ["team@example.com", "team@example.com"],
                "cc": ["audit@example.com"],
                "snippet": "Need a follow-up",
            }
        )

        self.assertEqual(normalized["subject"], "(no subject)")
        self.assertEqual(normalized["to"], ["team@example.com"])
        self.assertEqual(normalized["cc"], ["audit@example.com"])
        self.assertEqual(normalized["snippet"], "Need a follow-up")

    def test_build_email_triage_prompt_includes_core_fields(self) -> None:
        prompt = build_email_triage_prompt(
            {
                "account": "ops@example.com",
                "mailbox": "inbox",
                "thread_id": "thread-123",
                "message_id": "msg-123",
                "subject": "Need invoice copy",
                "from": "Alex <alex@example.com>",
                "to": ["ops@example.com"],
                "cc": [],
                "received_at": "2026-04-12T10:00:00+00:00",
                "snippet": "Can you resend the invoice?",
                "text_body": "Hello, can you resend the invoice PDF?",
            }
        )

        self.assertIn("Review this email for narrow triage.", prompt)
        self.assertIn("Subject: Need invoice copy", prompt)
        self.assertIn("From: Alex <alex@example.com>", prompt)
        self.assertIn("Email body:", prompt)

    def test_parse_email_triage_output_extracts_structured_fields(self) -> None:
        parsed = parse_email_triage_output(
            """
            Bottom line: Customer needs the invoice PDF resent.
            Urgency: Medium
            Suggested bucket: Billing
            Recommended next action: Confirm the invoice number and resend.
            Draft reply: Hi Alex,
            We can resend that invoice today.
            """
        )

        self.assertEqual(
            parsed["fields"],
            {
                "bottom_line": "Customer needs the invoice PDF resent.",
                "urgency": "Medium",
                "suggested_bucket": "Billing",
                "recommended_next_action": "Confirm the invoice number and resend.",
                "draft_reply": "Hi Alex,\nWe can resend that invoice today.",
            },
        )
        self.assertEqual(parsed["missing_fields"], [])

    def test_build_email_triage_artifact_value_wraps_source_and_triage(self) -> None:
        artifact_value = build_email_triage_artifact_value(
            {
                "account": "ops@example.com",
                "mailbox": "inbox",
                "thread_id": "thread-123",
                "message_id": "msg-123",
                "subject": "Need invoice copy",
                "from": "Alex <alex@example.com>",
                "to": ["ops@example.com"],
                "cc": [],
                "received_at": "2026-04-12T10:00:00+00:00",
                "snippet": "Can you resend the invoice?",
                "text_body": "Hello, can you resend the invoice PDF?",
            },
            "Bottom line: Resend the invoice.\nUrgency: Medium",
        )

        self.assertEqual(artifact_value["source"]["kind"], "email")
        self.assertEqual(artifact_value["email"]["subject"], "Need invoice copy")
        self.assertEqual(artifact_value["triage"]["fields"]["bottom_line"], "Resend the invoice.")
        self.assertEqual(
            artifact_value["triage"]["missing_fields"],
            ["suggested_bucket", "recommended_next_action", "draft_reply"],
        )

    def test_build_email_draft_handoff_value_wraps_approved_draft(self) -> None:
        handoff_value = build_email_draft_handoff_value(
            {
                "artifact_id": "artifact-123",
                "workflow_id": "workflow-123",
                "run_id": "run-123",
                "value": {
                    "source": {
                        "account": "ops@example.com",
                        "mailbox": "inbox",
                        "thread_id": "thread-123",
                        "message_id": "msg-123",
                    },
                    "email": {
                        "subject": "Need invoice copy",
                        "from": "Alex <alex@example.com>",
                        "to": ["ops@example.com"],
                        "cc": [],
                    },
                    "triage": {
                        "fields": {
                            "bottom_line": "Resend the invoice.",
                            "recommended_next_action": "Resend it today.",
                            "draft_reply": "Hi Alex,\nWe can resend that today.",
                        }
                    },
                },
            },
            {
                "approval_id": "approval-123",
                "status": "approved",
                "updated_at": "2026-04-12T10:00:00+00:00",
            },
        )

        self.assertEqual(handoff_value["source"]["triage_artifact_id"], "artifact-123")
        self.assertEqual(handoff_value["source"]["approval_id"], "approval-123")
        self.assertEqual(handoff_value["handoff"]["status"], "approved_for_manual_follow_through")
        self.assertIn("does not send email automatically", handoff_value["handoff"]["operator_guidance"])

    @patch("runtime.email_intake.list_artifacts_for_workflow")
    def test_find_email_draft_handoff_returns_latest_match(self, mock_list_artifacts_for_workflow) -> None:
        mock_list_artifacts_for_workflow.return_value = [
            {
                "artifact_id": "handoff-older",
                "kind": "email_draft_handoff",
                "updated_at": "2026-04-12T10:00:00+00:00",
                "metadata": {"triage_artifact_id": "artifact-123"},
            },
            {
                "artifact_id": "handoff-newer",
                "kind": "email_draft_handoff",
                "updated_at": "2026-04-12T11:00:00+00:00",
                "metadata": {"triage_artifact_id": "artifact-123"},
            },
        ]

        artifact = find_email_draft_handoff(
            {"artifact_id": "artifact-123", "workflow_id": "workflow-123", "run_id": "run-123", "value": {}}
        )

        self.assertEqual(artifact["artifact_id"], "handoff-newer")

    @patch("runtime.email_intake.list_approvals_for_workflow")
    def test_find_email_draft_approval_returns_latest_match(self, mock_list_approvals_for_workflow) -> None:
        mock_list_approvals_for_workflow.return_value = [
            {
                "approval_id": "approval-older",
                "status": "pending",
                "updated_at": "2026-04-12T10:00:00+00:00",
                "action": {"kind": "email_draft_review", "operation": "approve_draft_reply", "artifact_id": "artifact-123"},
            },
            {
                "approval_id": "approval-newer",
                "status": "approved",
                "updated_at": "2026-04-12T11:00:00+00:00",
                "action": {"kind": "email_draft_review", "operation": "approve_draft_reply", "artifact_id": "artifact-123"},
            },
        ]

        approval = find_email_draft_approval(
            {"artifact_id": "artifact-123", "workflow_id": "workflow-123", "run_id": "run-123", "value": {}}
        )

        self.assertEqual(approval["approval_id"], "approval-newer")

    @patch("runtime.email_intake.create_approval")
    @patch("runtime.email_intake.find_email_draft_approval")
    @patch("runtime.email_intake.load_workflow")
    @patch("runtime.email_intake.load_artifact")
    def test_request_email_draft_approval_creates_approval_for_draft_reply(
        self,
        mock_load_artifact,
        mock_load_workflow,
        mock_find_email_draft_approval,
        mock_create_approval,
    ) -> None:
        mock_load_artifact.return_value = {
            "artifact_id": "artifact-123",
            "workflow_id": "workflow-123",
            "run_id": "run-123",
            "kind": "email_triage",
            "value": {
                "source": {"message_id": "msg-123", "thread_id": "thread-123"},
                "email": {"subject": "Need invoice copy"},
                "triage": {"fields": {"draft_reply": "Hi Alex,\nWe can resend that today."}},
            },
        }
        mock_load_workflow.return_value = type("WorkflowStub", (), {"agent": "researcher"})()
        mock_find_email_draft_approval.return_value = None
        mock_create_approval.return_value = {
            "approval_id": "approval-123",
            "status": "pending",
            "agent": "researcher",
            "policy": "email_draft_review",
            "action": {"kind": "email_draft_review", "artifact_id": "artifact-123"},
            "reason": "Draft reply requires explicit approval before any outward email action",
            "requested_run_id": "run-123",
            "workflow_id": "workflow-123",
            "resumed_run_id": None,
            "created_at": "2026-04-12T10:00:00+00:00",
            "updated_at": "2026-04-12T10:00:00+00:00",
        }

        approval = request_email_draft_approval("artifact-123")

        self.assertEqual(approval["approval_id"], "approval-123")
        mock_create_approval.assert_called_once()
        self.assertEqual(
            mock_create_approval.call_args.kwargs["request"]["tool_args"]["draft_reply"],
            "Hi Alex,\nWe can resend that today.",
        )

    @patch("runtime.email_intake.find_email_draft_approval")
    @patch("runtime.email_intake.load_workflow")
    @patch("runtime.email_intake.load_artifact")
    def test_request_email_draft_approval_returns_existing_pending_approval(
        self,
        mock_load_artifact,
        mock_load_workflow,
        mock_find_email_draft_approval,
    ) -> None:
        mock_load_artifact.return_value = {
            "artifact_id": "artifact-123",
            "workflow_id": "workflow-123",
            "run_id": "run-123",
            "kind": "email_triage",
            "value": {"triage": {"fields": {"draft_reply": "Hi Alex"}}},
        }
        mock_load_workflow.return_value = type("WorkflowStub", (), {"agent": "researcher"})()
        mock_find_email_draft_approval.return_value = {
            "approval_id": "approval-123",
            "status": "pending",
            "agent": "researcher",
            "policy": "email_draft_review",
            "action": {"kind": "email_draft_review", "artifact_id": "artifact-123"},
            "reason": "Draft reply requires explicit approval before any outward email action",
            "requested_run_id": "run-123",
            "workflow_id": "workflow-123",
            "resumed_run_id": None,
            "created_at": "2026-04-12T10:00:00+00:00",
            "updated_at": "2026-04-12T10:00:00+00:00",
        }

        approval = request_email_draft_approval("artifact-123")

        self.assertEqual(approval["approval_id"], "approval-123")

    @patch("runtime.email_intake.load_workflow")
    @patch("runtime.email_intake.load_artifact")
    def test_request_email_draft_approval_requires_draft_reply(
        self,
        mock_load_artifact,
        mock_load_workflow,
    ) -> None:
        mock_load_artifact.return_value = {
            "artifact_id": "artifact-123",
            "workflow_id": "workflow-123",
            "run_id": "run-123",
            "kind": "email_triage",
            "value": {"triage": {"fields": {}}},
        }
        mock_load_workflow.return_value = type("WorkflowStub", (), {"agent": "researcher"})()

        with self.assertRaisesRegex(ValueError, "does not contain a draft reply"):
            request_email_draft_approval("artifact-123")

    @patch("runtime.email_intake.write_workflow")
    @patch("runtime.email_intake.register_artifact")
    @patch("runtime.email_intake.load_workflow")
    @patch("runtime.email_intake.create_artifact")
    @patch("runtime.email_intake.find_email_draft_handoff")
    @patch("runtime.email_intake.find_email_draft_approval")
    @patch("runtime.email_intake.load_artifact")
    def test_create_email_draft_handoff_creates_artifact_for_approved_draft(
        self,
        mock_load_artifact,
        mock_find_email_draft_approval,
        mock_find_email_draft_handoff,
        mock_create_artifact,
        mock_load_workflow,
        mock_register_artifact,
        mock_write_workflow,
    ) -> None:
        mock_load_artifact.return_value = {
            "artifact_id": "artifact-123",
            "workflow_id": "workflow-123",
            "run_id": "run-123",
            "kind": "email_triage",
            "value": {
                "source": {"message_id": "msg-123", "thread_id": "thread-123"},
                "email": {"subject": "Need invoice copy"},
                "triage": {
                    "fields": {
                        "bottom_line": "Resend the invoice.",
                        "draft_reply": "Hi Alex,\nWe can resend that today.",
                    }
                },
            },
        }
        mock_find_email_draft_approval.return_value = {
            "approval_id": "approval-123",
            "status": "approved",
            "updated_at": "2026-04-12T10:00:00+00:00",
        }
        mock_find_email_draft_handoff.return_value = None
        mock_create_artifact.return_value = {
            "artifact_id": "handoff-123",
            "workflow_id": "workflow-123",
            "run_id": "run-123",
            "name": "email-approved-draft",
            "kind": "email_draft_handoff",
            "value": {"handoff": {"draft_reply": "Hi Alex,\nWe can resend that today."}},
            "metadata": {"triage_artifact_id": "artifact-123"},
            "created_at": "2026-04-12T10:05:00+00:00",
            "updated_at": "2026-04-12T10:05:00+00:00",
        }

        handoff = create_email_draft_handoff("artifact-123")

        self.assertEqual(handoff["artifact_id"], "handoff-123")
        mock_create_artifact.assert_called_once()
        self.assertEqual(mock_create_artifact.call_args.kwargs["kind"], "email_draft_handoff")
        self.assertEqual(mock_create_artifact.call_args.kwargs["metadata"]["approval_id"], "approval-123")
        mock_load_workflow.assert_called_once_with("workflow-123")
        mock_register_artifact.assert_called_once()
        mock_write_workflow.assert_called_once()

    @patch("runtime.email_intake.find_email_draft_handoff")
    @patch("runtime.email_intake.find_email_draft_approval")
    @patch("runtime.email_intake.load_artifact")
    def test_create_email_draft_handoff_returns_existing_handoff(
        self,
        mock_load_artifact,
        mock_find_email_draft_approval,
        mock_find_email_draft_handoff,
    ) -> None:
        mock_load_artifact.return_value = {
            "artifact_id": "artifact-123",
            "workflow_id": "workflow-123",
            "run_id": "run-123",
            "kind": "email_triage",
            "value": {"triage": {"fields": {"draft_reply": "Hi Alex"}}},
        }
        mock_find_email_draft_approval.return_value = {"approval_id": "approval-123", "status": "approved"}
        mock_find_email_draft_handoff.return_value = {
            "artifact_id": "handoff-123",
            "workflow_id": "workflow-123",
            "run_id": "run-123",
            "name": "email-approved-draft",
            "kind": "email_draft_handoff",
            "metadata": {"triage_artifact_id": "artifact-123"},
            "created_at": "2026-04-12T10:05:00+00:00",
            "updated_at": "2026-04-12T10:05:00+00:00",
        }

        handoff = create_email_draft_handoff("artifact-123")

        self.assertEqual(handoff["artifact_id"], "handoff-123")

    @patch("runtime.email_intake.find_email_draft_approval")
    @patch("runtime.email_intake.load_artifact")
    def test_create_email_draft_handoff_requires_approved_review(
        self,
        mock_load_artifact,
        mock_find_email_draft_approval,
    ) -> None:
        mock_load_artifact.return_value = {
            "artifact_id": "artifact-123",
            "workflow_id": "workflow-123",
            "run_id": "run-123",
            "kind": "email_triage",
            "value": {"triage": {"fields": {"draft_reply": "Hi Alex"}}},
        }
        mock_find_email_draft_approval.return_value = {"approval_id": "approval-123", "status": "pending"}

        with self.assertRaisesRegex(ValueError, "requires an approved draft review"):
            create_email_draft_handoff("artifact-123")

    @patch("runtime.email_intake.write_workflow")
    @patch("runtime.email_intake.register_artifact")
    @patch("runtime.email_intake.load_workflow")
    @patch("runtime.email_intake.create_artifact")
    def test_persist_email_triage_artifact_registers_workflow_artifact(
        self,
        mock_create_artifact,
        mock_load_workflow,
        mock_register_artifact,
        mock_write_workflow,
    ) -> None:
        mock_create_artifact.return_value = {
            "artifact_id": "artifact-123",
            "workflow_id": "workflow-123",
            "run_id": "run-123",
            "name": "email-triage",
            "kind": "email_triage",
            "value": {"triage": {"fields": {"bottom_line": "Resend the invoice."}}},
            "metadata": {},
            "created_at": "2026-04-12T10:00:00+00:00",
            "updated_at": "2026-04-12T10:00:00+00:00",
        }
        workflow_result = {
            "status": "success",
            "output": "Bottom line: Resend the invoice.\nUrgency: Medium",
            "workflow": {"workflow_id": "workflow-123", "latest_run_id": "run-123", "artifacts": []},
            "artifacts": [],
        }

        artifact = persist_email_triage_artifact(
            {
                "account": "ops@example.com",
                "mailbox": "inbox",
                "thread_id": "thread-123",
                "message_id": "msg-123",
                "subject": "Need invoice copy",
                "from": "Alex <alex@example.com>",
                "to": ["ops@example.com"],
                "cc": [],
                "received_at": "2026-04-12T10:00:00+00:00",
                "snippet": "Can you resend the invoice?",
                "text_body": "Hello, can you resend the invoice PDF?",
            },
            workflow_result,
        )

        self.assertEqual(artifact["artifact_id"], "artifact-123")
        mock_create_artifact.assert_called_once()
        mock_load_workflow.assert_called_once_with("workflow-123")
        mock_register_artifact.assert_called_once()
        mock_write_workflow.assert_called_once()
        self.assertEqual(workflow_result["artifacts"][0]["artifact_id"], "artifact-123")
        self.assertEqual(workflow_result["workflow"]["artifacts"][0]["artifact_id"], "artifact-123")

    @patch("runtime.email_intake.persist_email_triage_artifact")
    @patch("runtime.email_intake.append_session_message")
    @patch("runtime.email_intake.create_session")
    def test_intake_email_creates_session_and_appends_triage_message(
        self,
        mock_create_session,
        mock_append_session_message,
        mock_persist_email_triage_artifact,
    ) -> None:
        mock_create_session.return_value = {
            "session_id": "session-123",
            "session_token": "token-123",
        }
        mock_persist_email_triage_artifact.return_value = {
            "artifact_id": "artifact-123",
            "workflow_id": "workflow-123",
            "run_id": "run-123",
            "name": "email-triage",
            "kind": "email_triage",
            "metadata": {},
            "created_at": "2026-04-12T10:00:00+00:00",
            "updated_at": "2026-04-12T10:00:00+00:00",
        }
        mock_append_session_message.return_value = {
            "session": {"session_id": "session-123", "status": "active"},
            "workflow_result": {"status": "success", "output": "Bottom line: triage"},
        }

        response = intake_email(
            {
                "account": "ops@example.com",
                "message_id": "msg-123",
                "subject": "Need invoice copy",
                "from": "Alex <alex@example.com>",
                "text_body": "Please resend the invoice.",
            }
        )

        self.assertTrue(response["session_created"])
        self.assertEqual(response["session_id"], "session-123")
        self.assertEqual(response["session_token"], "token-123")
        self.assertEqual(response["triage_artifact"]["artifact_id"], "artifact-123")
        self.assertEqual(response["structured_output"]["triage"]["fields"]["bottom_line"], "triage")
        mock_create_session.assert_called_once()
        append_kwargs = mock_append_session_message.call_args.kwargs
        self.assertEqual(append_kwargs["agent"], "researcher")
        self.assertIn("Need invoice copy", append_kwargs["content"])
        self.assertEqual(append_kwargs["metadata"]["source"]["kind"], "email")

    @patch("runtime.email_intake.persist_email_triage_artifact")
    @patch("runtime.email_intake.append_session_message")
    @patch("runtime.email_intake.create_session")
    def test_intake_email_uses_existing_session_when_provided(
        self,
        mock_create_session,
        mock_append_session_message,
        mock_persist_email_triage_artifact,
    ) -> None:
        mock_persist_email_triage_artifact.return_value = None
        mock_append_session_message.return_value = {
            "session": {"session_id": "session-123", "status": "active"},
            "workflow_result": {"status": "success", "output": "Bottom line: triage"},
        }

        response = intake_email(
            {
                "account": "ops@example.com",
                "message_id": "msg-123",
                "subject": "Need invoice copy",
                "snippet": "Please resend the invoice.",
            },
            session_id="session-123",
            agent="default",
        )

        self.assertFalse(response["session_created"])
        self.assertEqual(response["session_id"], "session-123")
        mock_create_session.assert_not_called()
        append_kwargs = mock_append_session_message.call_args.kwargs
        self.assertEqual(append_kwargs["agent"], "default")


if __name__ == "__main__":
    unittest.main()
