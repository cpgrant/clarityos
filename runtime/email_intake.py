import re
from typing import Any

from runtime.approval import approval_summary, create_approval, list_approvals_for_workflow
from runtime.artifact import artifact_summary, create_artifact, list_artifacts_for_workflow, load_artifact
from runtime.session import append_session_message, create_session
from runtime.workflow import load_workflow, normalize_optional_string, register_artifact, write_workflow


EMAIL_BODY_LIMIT = 12_000
EMAIL_SNIPPET_LIMIT = 280
EMAIL_SUBJECT_FALLBACK = "(no subject)"
TRIAGE_FIELD_PATTERNS = {
    "bottom_line": "bottom line",
    "urgency": "urgency",
    "suggested_bucket": "suggested bucket",
    "recommended_next_action": "recommended next action",
    "draft_reply": "draft reply",
}
TRIAGE_FIELD_ORDER = [
    "bottom_line",
    "urgency",
    "suggested_bucket",
    "recommended_next_action",
    "draft_reply",
]
EMAIL_DRAFT_APPROVAL_POLICY = "email_draft_review"
EMAIL_DRAFT_APPROVAL_REASON = "Draft reply requires explicit approval before any outward email action"
EMAIL_DRAFT_HANDOFF_KIND = "email_draft_handoff"


def normalize_non_empty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Email intake `{field_name}` must be a non-empty string")
    return value.strip()


def normalize_optional_string_list(value: object, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Email intake `{field_name}` must be a list of strings")

    normalized: list[str] = []
    seen = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"Email intake `{field_name}` must contain non-empty strings")
        entry = item.strip()
        if entry in seen:
            continue
        normalized.append(entry)
        seen.add(entry)
    return normalized


def truncate_text(value: str, *, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def normalize_email_payload(payload: dict | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Email intake payload must be an object")

    text_body = normalize_optional_string(payload.get("text_body"), field_name="text_body")
    snippet = normalize_optional_string(payload.get("snippet"), field_name="snippet")
    if text_body is None and snippet is None:
        raise ValueError("Email intake requires either `text_body` or `snippet`")

    normalized_body = truncate_text(text_body, limit=EMAIL_BODY_LIMIT) if text_body is not None else None
    normalized_snippet = truncate_text(
        snippet or (normalized_body or ""),
        limit=EMAIL_SNIPPET_LIMIT,
    )
    subject = normalize_optional_string(payload.get("subject"), field_name="subject") or EMAIL_SUBJECT_FALLBACK

    return {
        "account": normalize_non_empty_string(payload.get("account"), field_name="account"),
        "mailbox": normalize_optional_string(payload.get("mailbox"), field_name="mailbox"),
        "thread_id": normalize_optional_string(payload.get("thread_id"), field_name="thread_id"),
        "message_id": normalize_non_empty_string(payload.get("message_id"), field_name="message_id"),
        "subject": subject,
        "from": normalize_optional_string(payload.get("from"), field_name="from"),
        "to": normalize_optional_string_list(payload.get("to"), field_name="to"),
        "cc": normalize_optional_string_list(payload.get("cc"), field_name="cc"),
        "received_at": normalize_optional_string(payload.get("received_at"), field_name="received_at"),
        "snippet": normalized_snippet,
        "text_body": normalized_body,
    }


def default_session_title(email: dict[str, Any]) -> str:
    sender = email.get("from") or email.get("account")
    subject = email.get("subject") or EMAIL_SUBJECT_FALLBACK
    return f"{sender}: {subject}"


def build_email_triage_prompt(email: dict[str, Any]) -> str:
    lines = [
        "Review this email for narrow triage.",
        "Return a concise response with:",
        "- Bottom line",
        "- Urgency",
        "- Suggested bucket",
        "- Recommended next action",
        "- Draft reply only if a reply is appropriate",
        "",
        f"Account: {email['account']}",
        f"Mailbox: {email.get('mailbox') or 'inbox'}",
        f"Thread ID: {email.get('thread_id') or 'unknown'}",
        f"Message ID: {email['message_id']}",
        f"Subject: {email['subject']}",
        f"From: {email.get('from') or 'unknown'}",
    ]
    if email.get("to"):
        lines.append(f"To: {', '.join(email['to'])}")
    if email.get("cc"):
        lines.append(f"Cc: {', '.join(email['cc'])}")
    if email.get("received_at"):
        lines.append(f"Received At: {email['received_at']}")
    if email.get("snippet"):
        lines.extend(["", f"Snippet: {email['snippet']}"])
    if email.get("text_body"):
        lines.extend(["", "Email body:", email["text_body"]])
    return "\n".join(lines)


def parse_email_triage_output(output: str | None) -> dict[str, Any]:
    normalized_output = normalize_optional_string(output, field_name="output")
    if normalized_output is None:
        return {
            "raw_output": None,
            "fields": {},
            "missing_fields": list(TRIAGE_FIELD_ORDER),
        }

    label_pattern = "|".join(re.escape(label) for label in TRIAGE_FIELD_PATTERNS.values())
    section_pattern = re.compile(
        rf"^\s*-?\s*(?P<label>{label_pattern})\s*:\s*(?P<value>.*)$",
        flags=re.IGNORECASE,
    )

    parsed_fields: dict[str, list[str]] = {}
    current_field: str | None = None
    for raw_line in normalized_output.splitlines():
        line = raw_line.strip()
        if not line:
            if current_field is not None and parsed_fields.get(current_field):
                parsed_fields[current_field].append("")
            continue

        match = section_pattern.match(line)
        if match is not None:
            normalized_label = match.group("label").strip().lower()
            current_field = next(
                field_name
                for field_name, label in TRIAGE_FIELD_PATTERNS.items()
                if label == normalized_label
            )
            parsed_fields.setdefault(current_field, [])
            value = match.group("value").strip()
            if value:
                parsed_fields[current_field].append(value)
            continue

        if current_field is not None:
            parsed_fields.setdefault(current_field, []).append(line)

    fields = {}
    for field_name in TRIAGE_FIELD_ORDER:
        value = "\n".join(parsed_fields.get(field_name, [])).strip()
        if value:
            fields[field_name] = value

    return {
        "raw_output": normalized_output,
        "fields": fields,
        "missing_fields": [field_name for field_name in TRIAGE_FIELD_ORDER if field_name not in fields],
    }


def build_email_triage_artifact_value(email: dict[str, Any], output: str | None) -> dict[str, Any]:
    parsed = parse_email_triage_output(output)
    return {
        "source": {
            "kind": "email",
            "account": email["account"],
            "mailbox": email.get("mailbox"),
            "thread_id": email.get("thread_id"),
            "message_id": email["message_id"],
            "received_at": email.get("received_at"),
        },
        "email": {
            "subject": email["subject"],
            "from": email.get("from"),
            "to": list(email.get("to") or []),
            "cc": list(email.get("cc") or []),
            "snippet": email.get("snippet"),
        },
        "triage": parsed,
    }


def email_draft_reply(value: dict[str, Any]) -> str | None:
    triage = value.get("triage") if isinstance(value.get("triage"), dict) else {}
    fields = triage.get("fields") if isinstance(triage.get("fields"), dict) else {}
    return normalize_optional_string(fields.get("draft_reply"), field_name="draft_reply")


def load_email_triage_artifact(artifact_id: str) -> dict[str, Any]:
    artifact = load_artifact(artifact_id)
    if artifact.get("kind") != "email_triage":
        raise ValueError(f"Artifact `{artifact_id}` is not an email triage artifact")
    value = artifact.get("value")
    if not isinstance(value, dict):
        raise ValueError(f"Artifact `{artifact_id}` is missing structured email triage content")
    return artifact


def email_draft_approval_action(artifact: dict[str, Any]) -> dict[str, Any]:
    value = artifact.get("value") or {}
    source = value.get("source") if isinstance(value.get("source"), dict) else {}
    email = value.get("email") if isinstance(value.get("email"), dict) else {}
    return {
        "kind": "email_draft_review",
        "operation": "approve_draft_reply",
        "artifact_id": artifact["artifact_id"],
        "workflow_id": artifact["workflow_id"],
        "run_id": artifact["run_id"],
        "message_id": source.get("message_id"),
        "thread_id": source.get("thread_id"),
        "subject": email.get("subject"),
    }


def find_email_draft_approval(artifact: dict[str, Any]) -> dict[str, Any] | None:
    action = email_draft_approval_action(artifact)
    matches = []
    for approval in list_approvals_for_workflow(artifact["workflow_id"]):
        approval_action = approval.get("action")
        if not isinstance(approval_action, dict):
            continue
        if (
            approval_action.get("kind") == action["kind"]
            and approval_action.get("operation") == action["operation"]
            and approval_action.get("artifact_id") == artifact["artifact_id"]
        ):
            matches.append(approval)
    if not matches:
        return None
    return max(matches, key=lambda approval: approval.get("updated_at") or approval.get("created_at") or "")


def request_email_draft_approval(artifact_id: str) -> dict[str, Any]:
    artifact = load_email_triage_artifact(artifact_id)
    workflow = load_workflow(artifact["workflow_id"])
    value = artifact.get("value") or {}
    draft_reply = email_draft_reply(value)
    if draft_reply is None:
        raise ValueError(f"Email triage artifact `{artifact_id}` does not contain a draft reply")

    existing = find_email_draft_approval(artifact)
    if existing is not None and existing.get("status") in {"pending", "approved", "resumed"}:
        return approval_summary(existing)

    email = value.get("email") if isinstance(value.get("email"), dict) else {}
    source = value.get("source") if isinstance(value.get("source"), dict) else {}
    approval = create_approval(
        run_id=artifact["run_id"],
        workflow_id=artifact["workflow_id"],
        agent=workflow.agent,
        policy_name=EMAIL_DRAFT_APPROVAL_POLICY,
        action=email_draft_approval_action(artifact),
        reason=EMAIL_DRAFT_APPROVAL_REASON,
        request={
            "input": "",
            "agent": workflow.agent,
            "tool": None,
            "tool_args": {
                "artifact_id": artifact["artifact_id"],
                "subject": email.get("subject"),
                "message_id": source.get("message_id"),
                "thread_id": source.get("thread_id"),
                "draft_reply": draft_reply,
            },
        },
    )
    return approval_summary(approval)


def build_email_draft_handoff_value(artifact: dict[str, Any], approval: dict[str, Any]) -> dict[str, Any]:
    value = artifact.get("value") if isinstance(artifact.get("value"), dict) else {}
    source = value.get("source") if isinstance(value.get("source"), dict) else {}
    email = value.get("email") if isinstance(value.get("email"), dict) else {}
    triage = value.get("triage") if isinstance(value.get("triage"), dict) else {}
    fields = triage.get("fields") if isinstance(triage.get("fields"), dict) else {}
    draft_reply = email_draft_reply(value)
    if draft_reply is None:
        raise ValueError(f"Email triage artifact `{artifact['artifact_id']}` does not contain a draft reply")

    return {
        "source": {
            "kind": "email_draft_handoff",
            "triage_artifact_id": artifact["artifact_id"],
            "approval_id": approval["approval_id"],
            "workflow_id": artifact["workflow_id"],
            "run_id": artifact["run_id"],
            "account": source.get("account"),
            "mailbox": source.get("mailbox"),
            "thread_id": source.get("thread_id"),
            "message_id": source.get("message_id"),
            "received_at": source.get("received_at"),
        },
        "email": {
            "subject": email.get("subject"),
            "from": email.get("from"),
            "to": list(email.get("to") or []),
            "cc": list(email.get("cc") or []),
            "snippet": email.get("snippet"),
        },
        "triage": {
            "bottom_line": fields.get("bottom_line"),
            "urgency": fields.get("urgency"),
            "suggested_bucket": fields.get("suggested_bucket"),
            "recommended_next_action": fields.get("recommended_next_action"),
        },
        "handoff": {
            "draft_reply": draft_reply,
            "status": "approved_for_manual_follow_through",
            "operator_guidance": "Use this approved draft for manual follow-through outside ClarityClaw. v1.8 still does not send email automatically.",
            "outward_action": "manual_only",
            "approved_at": approval.get("updated_at") or approval.get("created_at"),
        },
    }


def find_email_draft_handoff(artifact: dict[str, Any]) -> dict[str, Any] | None:
    matches = []
    for candidate in list_artifacts_for_workflow(artifact["workflow_id"]):
        if candidate.get("kind") != EMAIL_DRAFT_HANDOFF_KIND:
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        if metadata.get("triage_artifact_id") == artifact["artifact_id"]:
            matches.append(candidate)
            continue
        value = candidate.get("value") if isinstance(candidate.get("value"), dict) else {}
        source = value.get("source") if isinstance(value.get("source"), dict) else {}
        if source.get("triage_artifact_id") == artifact["artifact_id"]:
            matches.append(candidate)
    if not matches:
        return None
    return max(matches, key=lambda candidate: candidate.get("updated_at") or candidate.get("created_at") or "")


def create_email_draft_handoff(artifact_id: str) -> dict[str, Any]:
    artifact = load_email_triage_artifact(artifact_id)
    approval = find_email_draft_approval(artifact)
    if approval is None or approval.get("status") != "approved":
        raise ValueError(
            f"Email triage artifact `{artifact_id}` requires an approved draft review before handoff is created"
        )

    existing = find_email_draft_handoff(artifact)
    if existing is not None:
        return artifact_summary(existing)

    handoff_value = build_email_draft_handoff_value(artifact, approval)
    handoff = create_artifact(
        workflow_id=artifact["workflow_id"],
        run_id=artifact["run_id"],
        name="email-approved-draft",
        kind=EMAIL_DRAFT_HANDOFF_KIND,
        value=handoff_value,
        metadata={
            "source": "email_draft_review",
            "triage_artifact_id": artifact["artifact_id"],
            "approval_id": approval["approval_id"],
            "message_id": handoff_value["source"].get("message_id"),
            "thread_id": handoff_value["source"].get("thread_id"),
        },
    )
    summary = artifact_summary(handoff)
    workflow = load_workflow(artifact["workflow_id"])
    register_artifact(workflow, summary)
    write_workflow(workflow)
    return summary


def email_session_metadata(email: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": {
            "kind": "email",
            "account": email["account"],
            "mailbox": email.get("mailbox"),
            "thread_id": email.get("thread_id"),
        }
    }


def email_message_metadata(email: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": {
            "kind": "email",
            "account": email["account"],
            "mailbox": email.get("mailbox"),
            "thread_id": email.get("thread_id"),
            "message_id": email["message_id"],
            "received_at": email.get("received_at"),
        },
        "email": {
            "subject": email["subject"],
            "from": email.get("from"),
            "to": list(email.get("to") or []),
            "cc": list(email.get("cc") or []),
            "snippet": email.get("snippet"),
        },
    }


def persist_email_triage_artifact(email: dict[str, Any], workflow_result: dict[str, Any]) -> dict[str, Any] | None:
    if workflow_result.get("status") != "success":
        return None

    workflow_payload = workflow_result.get("workflow")
    if not isinstance(workflow_payload, dict):
        return None

    workflow_id = normalize_optional_string(workflow_payload.get("workflow_id"), field_name="workflow_id")
    run_id = normalize_optional_string(
        workflow_payload.get("latest_run_id") or workflow_payload.get("run_id"),
        field_name="run_id",
    )
    output = normalize_optional_string(workflow_result.get("output"), field_name="output")
    if workflow_id is None or run_id is None or output is None:
        return None

    artifact = create_artifact(
        workflow_id=workflow_id,
        run_id=run_id,
        name="email-triage",
        kind="email_triage",
        value=build_email_triage_artifact_value(email, output),
        metadata={
            "source": "email_intake",
            "account": email["account"],
            "message_id": email["message_id"],
            "thread_id": email.get("thread_id"),
        },
    )
    summary = artifact_summary(artifact)

    workflow = load_workflow(workflow_id)
    register_artifact(workflow, summary)
    write_workflow(workflow)

    workflow_result.setdefault("artifacts", []).append(dict(summary))
    workflow_payload.setdefault("artifacts", []).append(dict(summary))
    return artifact


def intake_email(
    payload: dict | None,
    *,
    agent: str = "researcher",
    session_id: str | None = None,
) -> dict[str, Any]:
    email = normalize_email_payload(payload)
    normalized_agent = normalize_non_empty_string(agent, field_name="agent")
    existing_session_id = normalize_optional_string(session_id, field_name="session_id")

    session_created = False
    session_token = None
    if existing_session_id is None:
        created = create_session(
            title=default_session_title(email),
            agent=normalized_agent,
            metadata=email_session_metadata(email),
            surface="email_intake",
        )
        existing_session_id = created["session_id"]
        session_token = created["session_token"]
        session_created = True

    result = append_session_message(
        existing_session_id,
        content=build_email_triage_prompt(email),
        agent=normalized_agent,
        metadata=email_message_metadata(email),
    )
    triage_artifact = persist_email_triage_artifact(email, result["workflow_result"])
    response = {
        "email": email,
        "session_id": existing_session_id,
        "session_created": session_created,
        "session": result["session"],
        "workflow_result": result["workflow_result"],
        "structured_output": build_email_triage_artifact_value(email, result["workflow_result"].get("output")),
    }
    if triage_artifact is not None:
        response["triage_artifact"] = artifact_summary(triage_artifact)
    if session_token is not None:
        response["session_token"] = session_token
    return response
