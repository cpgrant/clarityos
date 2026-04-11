import hmac
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from runtime.agent import AGENTS_CONFIG_ENV_VAR, agents_config_path
from runtime.artifact import ARTIFACT_DIR, ARTIFACT_STATE_SCHEMA, artifact_path, load_artifact
from runtime.approval import APPROVAL_DIR, APPROVAL_STATE_SCHEMA, abort_approval, approval_path, approve_approval, deny_approval, get_approval
from runtime.control_plane import (
    operator_dashboard_view,
    queue_health_view,
    recover_workflow,
    session_control_view,
    worker_health_view,
    workflow_control_view,
    workflow_incident_view,
    workflow_incident_summary_view,
)
from runtime.errors import (
    ApprovalStateError,
    BudgetExceededError,
    DelegationDeniedError,
    OperatorAuthError,
    PolicyDeniedError,
    SessionAuthError,
)
from runtime.memory import MEMORY_DIR, MEMORY_STATE_SCHEMA, delete_memory, list_memories, load_memory, memory_path
from runtime.model import MODELS_CONFIG_ENV_VAR, models_config_path
from runtime.policy import (
    ALLOW_POLICY_OVERRIDES_ENV_VAR,
    POLICIES_CONFIG_ENV_VAR,
    PRODUCTION_ENV_VAR,
    allow_agent_policy_overrides,
    policies_config_path,
    production_mode_enabled,
    runtime_environment,
)
from runtime.queue import (
    JOB_DIR,
    JOB_STATE_SCHEMA,
    create_job,
    job_path,
    list_jobs,
    load_job,
    promote_due_jobs,
    prune_jobs,
    queue_summary,
    repair_stale_job_state,
    reschedule_job,
)
from runtime.session import (
    DEFAULT_SESSION_AUTH_HEADER,
    SESSION_DIR,
    SESSION_STATE_SCHEMA,
    archive_session,
    append_session_message as append_message_to_session,
    compact_session_continuity,
    create_session,
    list_sessions,
    load_session,
    prune_sessions,
    session_snapshot,
    session_path,
    verify_session_access,
)
from runtime.storage import STATE_ROOT_ENV_VAR, storage_profile
from runtime.state import (
    PERSISTED_STATE_VERSION,
    inspect_state_payload,
    migrate_state_directory,
    migrate_state_payload,
)
from runtime.worker import (
    WORKER_DIR,
    WORKER_STATE_SCHEMA,
    cancel_job_execution,
    claim_next_job,
    heartbeat_worker,
    list_workers,
    load_worker,
    reclaim_expired_leases,
    repair_orphaned_workers,
    register_worker,
    reset_worker,
    run_claimed_job,
    run_next_job,
    worker_path,
)
from runtime.workflow import WORKFLOW_DIR, WORKFLOW_STATE_SCHEMA, workflow_path
from runtime.workflow_runner import replay_workflow, resume_workflow, safe_resume_workflow, start_child_workflow, start_workflow

BASE_DIR = Path(__file__).resolve().parent.parent
ASSISTANT_UI_PATH = BASE_DIR / "ui" / "assistant.html"
OPERATOR_UI_PATH = BASE_DIR / "ui" / "operator.html"
WIDGET_UI_PATH = BASE_DIR / "ui" / "widget.html"
WIDGET_SCRIPT_PATH = BASE_DIR / "ui" / "widget.js"

app = FastAPI(title="ClarityOS", version="1.6.0")
OPERATOR_TOKEN_ENV_VAR = "CLARITYOS_OPERATOR_TOKEN"
OPERATOR_AUTH_HEADER = "X-Operator-Token"
SESSION_AUTH_HEADER = DEFAULT_SESSION_AUTH_HEADER
WIDGET_ALLOWED_ORIGINS_ENV_VAR = "CLARITYOS_WIDGET_ALLOWED_ORIGINS"
WIDGET_ENABLED_ENV_VAR = "CLARITYOS_WIDGET_ENABLED"
WIDGET_ALLOWED_AGENTS_ENV_VAR = "CLARITYOS_WIDGET_ALLOWED_AGENTS"
WIDGET_BRAND_NAME_ENV_VAR = "CLARITYOS_WIDGET_BRAND_NAME"
WIDGET_BRAND_TAGLINE_ENV_VAR = "CLARITYOS_WIDGET_BRAND_TAGLINE"
WIDGET_BRAND_ACCENT_ENV_VAR = "CLARITYOS_WIDGET_BRAND_ACCENT"
WIDGET_BRAND_AGENT_ENV_VAR = "CLARITYOS_WIDGET_DEFAULT_AGENT"
WIDGET_LAUNCHER_LABEL_ENV_VAR = "CLARITYOS_WIDGET_LAUNCHER_LABEL"
WIDGET_LAUNCHER_POSITION_ENV_VAR = "CLARITYOS_WIDGET_LAUNCHER_POSITION"
WIDGET_LAUNCHER_DEFAULT_OPEN_ENV_VAR = "CLARITYOS_WIDGET_LAUNCHER_DEFAULT_OPEN"


@app.get("/status")
def status() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/operator/auth")
def operator_auth():
    return operator_auth_status()


@app.get("/operator/profile")
def operator_profile(
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return operator_profile_status()
    except Exception as exc:
        return error_response(exc)


@app.get("/operator/dashboard")
def operator_dashboard(
    session_limit: int = 20,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return operator_dashboard_view(session_limit=session_limit)
    except Exception as exc:
        return error_response(exc)


def error_status_code(exc: Exception) -> int:
    if isinstance(exc, FileNotFoundError):
        return 404
    if isinstance(exc, (OperatorAuthError, SessionAuthError)):
        return 401
    if isinstance(exc, (DelegationDeniedError, PolicyDeniedError)):
        return 403
    if isinstance(exc, ApprovalStateError):
        return 409
    if isinstance(exc, BudgetExceededError):
        return 429
    if isinstance(exc, ValueError):
        return 400
    return 500


def error_response(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=error_status_code(exc),
        content={
            "status": "error",
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        },
    )


def assistant_html() -> str:
    return ASSISTANT_UI_PATH.read_text(encoding="utf-8")


def operator_html() -> str:
    return OPERATOR_UI_PATH.read_text(encoding="utf-8")


def widget_html() -> str:
    return WIDGET_UI_PATH.read_text(encoding="utf-8")


def widget_script() -> str:
    return WIDGET_SCRIPT_PATH.read_text(encoding="utf-8")


def normalize_origin_list(raw_value: str | None) -> list[str]:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return []

    origins = []
    seen = set()
    for item in raw_value.split(","):
        value = item.strip()
        if not value:
            continue
        if value == "*":
            return ["*"]
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                f"Widget allowed origins must be absolute http/https origins, got `{value}`"
            )
        normalized = f"{parsed.scheme}://{parsed.netloc}"
        if normalized not in seen:
            origins.append(normalized)
            seen.add(normalized)
    return origins


def widget_branding_config() -> dict[str, str]:
    return {
        "name": os.getenv(WIDGET_BRAND_NAME_ENV_VAR, "ClarityOS Assistant"),
        "tagline": os.getenv(
            WIDGET_BRAND_TAGLINE_ENV_VAR,
            "A thin web gateway over the existing session runtime.",
        ),
        "accent": os.getenv(WIDGET_BRAND_ACCENT_ENV_VAR, "#176b52"),
        "default_agent": os.getenv(WIDGET_BRAND_AGENT_ENV_VAR, "researcher"),
        "launcher_label": os.getenv(WIDGET_LAUNCHER_LABEL_ENV_VAR, "Ask"),
    }


def env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_csv_values(raw_value: str | None) -> list[str]:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return []

    values = []
    seen = set()
    for item in raw_value.split(","):
        value = item.strip()
        if not value or value in seen:
            continue
        values.append(value)
        seen.add(value)
    return values


def widget_allowed_agents() -> list[str]:
    configured = normalize_csv_values(os.getenv(WIDGET_ALLOWED_AGENTS_ENV_VAR))
    default_agent = widget_branding_config()["default_agent"]
    if not configured:
        return [default_agent]
    remaining = [agent for agent in configured if agent != default_agent]
    return [default_agent, *remaining]


def widget_launcher_config() -> dict[str, object]:
    position = os.getenv(WIDGET_LAUNCHER_POSITION_ENV_VAR, "right").strip().lower()
    if position not in {"left", "right"}:
        raise ValueError(
            f"Widget launcher position must be `left` or `right`, got `{position}`"
        )
    return {
        "position": position,
        "default_open": env_bool(WIDGET_LAUNCHER_DEFAULT_OPEN_ENV_VAR, default=False),
    }


def widget_enabled() -> bool:
    return env_bool(WIDGET_ENABLED_ENV_VAR, default=True)


def resolve_widget_agent(requested_agent: str | None, allowed_agents: list[str]) -> str:
    requested = requested_agent.strip() if isinstance(requested_agent, str) else ""
    if requested and requested in allowed_agents:
        return requested
    if requested and not allowed_agents:
        return requested
    if allowed_agents:
        return allowed_agents[0]
    return widget_branding_config()["default_agent"]


def widget_frame_ancestors(allowed_origins: list[str]) -> str:
    if "*" in allowed_origins:
        return "*"
    if not allowed_origins:
        return "'self'"
    return " ".join(allowed_origins)


def widget_security_headers(config: dict[str, object]) -> dict[str, str]:
    allowed_origins = config["allowed_origins"]
    headers = {
        "Content-Security-Policy": f"frame-ancestors {widget_frame_ancestors(allowed_origins)};",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Cache-Control": "no-store",
    }
    if not allowed_origins:
        headers["X-Frame-Options"] = "SAMEORIGIN"
    return headers


def widget_origin_allowed(
    requested_origin: str | None,
    *,
    service_origin: str,
    allowed_origins: list[str],
) -> bool:
    if requested_origin is None:
        return True
    if "*" in allowed_origins:
        return True
    if not allowed_origins:
        return requested_origin == service_origin
    return requested_origin in allowed_origins


def widget_runtime_config(
    *,
    service_origin: str,
    requested_origin: str | None = None,
) -> dict[str, object]:
    allowed_origins = normalize_origin_list(os.getenv(WIDGET_ALLOWED_ORIGINS_ENV_VAR))
    allowed_agents = widget_allowed_agents()
    branding = widget_branding_config()
    return {
        "enabled": widget_enabled(),
        "service_origin": service_origin,
        "allowed_origins": allowed_origins,
        "allowed_agents": allowed_agents,
        "origin_restriction_enabled": True,
        "requested_origin": requested_origin,
        "requested_origin_allowed": widget_origin_allowed(
            requested_origin,
            service_origin=service_origin,
            allowed_origins=allowed_origins,
        ),
        "branding": {
            **branding,
            "default_agent": resolve_widget_agent(branding["default_agent"], allowed_agents),
        },
        "launcher": widget_launcher_config(),
        "env_vars": {
            "enabled": WIDGET_ENABLED_ENV_VAR,
            "allowed_origins": WIDGET_ALLOWED_ORIGINS_ENV_VAR,
            "allowed_agents": WIDGET_ALLOWED_AGENTS_ENV_VAR,
            "brand_name": WIDGET_BRAND_NAME_ENV_VAR,
            "brand_tagline": WIDGET_BRAND_TAGLINE_ENV_VAR,
            "brand_accent": WIDGET_BRAND_ACCENT_ENV_VAR,
            "default_agent": WIDGET_BRAND_AGENT_ENV_VAR,
            "launcher_label": WIDGET_LAUNCHER_LABEL_ENV_VAR,
            "launcher_position": WIDGET_LAUNCHER_POSITION_ENV_VAR,
            "launcher_default_open": WIDGET_LAUNCHER_DEFAULT_OPEN_ENV_VAR,
        },
    }


def render_widget_html(config: dict[str, object]) -> str:
    html = widget_html()
    injected = (
        "<script>"
        f"window.__CLARITYOS_WIDGET_CONFIG__ = {json.dumps(config)};"
        "</script>"
    )
    return html.replace("</head>", f"  {injected}\n</head>", 1)


def widget_denied_html(config: dict[str, object]) -> str:
    branding = config["branding"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{branding['name']}</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: Georgia, "Times New Roman", serif;
      background: linear-gradient(180deg, #f9f4ec 0%, #f3eee5 100%);
      color: #1f1a15;
    }}
    article {{
      max-width: 420px;
      margin: 24px;
      padding: 24px;
      border-radius: 20px;
      background: rgba(255, 250, 244, 0.94);
      border: 1px solid #dfd2c0;
      box-shadow: 0 18px 40px rgba(31, 26, 21, 0.12);
    }}
    h1 {{ margin: 0 0 10px; font-size: 28px; }}
    p {{ margin: 0 0 10px; line-height: 1.5; color: #665b4d; }}
    code {{
      display: inline-block;
      background: #f0e7d8;
      border-radius: 8px;
      padding: 2px 8px;
    }}
  </style>
</head>
<body>
  <article>
    <h1>Widget Origin Not Allowed</h1>
    <p>This embeddable widget is configured for a narrow set of hosts.</p>
    <p>Requested parent origin: <code>{config.get("requested_origin") or "unknown"}</code></p>
    <p>Set <code>{WIDGET_ALLOWED_ORIGINS_ENV_VAR}</code> to allow this host explicitly.</p>
  </article>
</body>
</html>"""


def widget_disabled_html(config: dict[str, object]) -> str:
    branding = config["branding"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{branding['name']}</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: Georgia, "Times New Roman", serif;
      background: linear-gradient(180deg, #f9f4ec 0%, #f3eee5 100%);
      color: #1f1a15;
    }}
    article {{
      max-width: 420px;
      margin: 24px;
      padding: 24px;
      border-radius: 20px;
      background: rgba(255, 250, 244, 0.94);
      border: 1px solid #dfd2c0;
      box-shadow: 0 18px 40px rgba(31, 26, 21, 0.12);
    }}
    h1 {{ margin: 0 0 10px; font-size: 28px; }}
    p {{ margin: 0 0 10px; line-height: 1.5; color: #665b4d; }}
    code {{
      display: inline-block;
      background: #f0e7d8;
      border-radius: 8px;
      padding: 2px 8px;
    }}
  </style>
</head>
<body>
  <article>
    <h1>Widget Disabled</h1>
    <p>This deployment has turned off the embeddable widget surface.</p>
    <p>Set <code>{WIDGET_ENABLED_ENV_VAR}=1</code> to re-enable it.</p>
  </article>
</body>
</html>"""


def operator_auth_enabled() -> bool:
    token = os.getenv(OPERATOR_TOKEN_ENV_VAR)
    return isinstance(token, str) and bool(token.strip())


def operator_auth_status() -> dict[str, object]:
    return {
        "enabled": operator_auth_enabled(),
        "header": OPERATOR_AUTH_HEADER,
        "env_var": OPERATOR_TOKEN_ENV_VAR,
    }


def session_auth_status() -> dict[str, object]:
    return {
        "header": SESSION_AUTH_HEADER,
    }


def operator_profile_status() -> dict[str, object]:
    profile = storage_profile()
    return {
        "environment": {
            "name": runtime_environment(),
            "production_mode": production_mode_enabled(),
        },
        "operator_auth": operator_auth_status(),
        "session_auth": session_auth_status(),
        "policy": {
            "allow_agent_overrides": allow_agent_policy_overrides(),
            "env_vars": {
                "runtime_environment": PRODUCTION_ENV_VAR,
                "allow_agent_policy_overrides": ALLOW_POLICY_OVERRIDES_ENV_VAR,
            },
        },
        "config": {
            "agents": {
                "path": str(agents_config_path()),
                "env_var": AGENTS_CONFIG_ENV_VAR,
            },
            "policies": {
                "path": str(policies_config_path()),
                "env_var": POLICIES_CONFIG_ENV_VAR,
            },
            "models": {
                "path": str(models_config_path()),
                "env_var": MODELS_CONFIG_ENV_VAR,
            },
            "widget": {
                "allowed_origins_env_var": WIDGET_ALLOWED_ORIGINS_ENV_VAR,
                "branding_env_vars": {
                    "name": WIDGET_BRAND_NAME_ENV_VAR,
                    "tagline": WIDGET_BRAND_TAGLINE_ENV_VAR,
                    "accent": WIDGET_BRAND_ACCENT_ENV_VAR,
                    "default_agent": WIDGET_BRAND_AGENT_ENV_VAR,
                    "launcher_label": WIDGET_LAUNCHER_LABEL_ENV_VAR,
                },
                "defaults": {
                    "allowed_origins": normalize_origin_list(os.getenv(WIDGET_ALLOWED_ORIGINS_ENV_VAR)),
                    "branding": widget_branding_config(),
                },
            },
        },
        "state": {
            "current_version": PERSISTED_STATE_VERSION,
            "root_env_var": STATE_ROOT_ENV_VAR,
            "root": profile["root"],
            "directories": profile["directories"],
            "guidance": profile["guidance"],
        },
    }


def require_operator_auth(operator_token: str | None) -> None:
    configured = os.getenv(OPERATOR_TOKEN_ENV_VAR)
    if not isinstance(configured, str) or not configured.strip():
        return
    if not operator_token_matches(operator_token):
        raise OperatorAuthError(
            f"Operator token is required via `{OPERATOR_AUTH_HEADER}`",
            header_name=OPERATOR_AUTH_HEADER,
        )


def operator_token_matches(operator_token: str | None) -> bool:
    configured = os.getenv(OPERATOR_TOKEN_ENV_VAR)
    if not isinstance(configured, str) or not configured.strip():
        return False
    candidate = operator_token.strip() if isinstance(operator_token, str) else ""
    return hmac.compare_digest(candidate, configured)


def require_session_or_operator_auth(
    session_id: str,
    session_token: str | None,
    operator_token: str | None,
):
    session = load_session(session_id)
    if operator_token_matches(operator_token):
        return session
    verify_session_access(session, session_token, header_name=SESSION_AUTH_HEADER)
    return session


@app.post("/run")
def run(payload: dict):
    try:
        return workflow_run(payload)
    except Exception as exc:
        return error_response(exc)


@app.get("/assistant")
def assistant_surface():
    try:
        return HTMLResponse(assistant_html())
    except Exception as exc:
        return error_response(exc)


@app.get("/operator")
def operator_surface():
    try:
        return HTMLResponse(operator_html())
    except Exception as exc:
        return error_response(exc)


@app.get("/widget")
def widget_surface(
    request: Request,
    parent_origin: str | None = None,
):
    try:
        service_origin = str(request.base_url).rstrip("/")
        config = widget_runtime_config(service_origin=service_origin, requested_origin=parent_origin)
        headers = widget_security_headers(config)
        if not config["enabled"]:
            return HTMLResponse(widget_disabled_html(config), status_code=404, headers=headers)
        if parent_origin is not None and not config["requested_origin_allowed"]:
            return HTMLResponse(widget_denied_html(config), status_code=403, headers=headers)
        return HTMLResponse(render_widget_html(config), headers=headers)
    except Exception as exc:
        return error_response(exc)


@app.get("/widget.js")
def widget_loader(request: Request):
    try:
        service_origin = str(request.base_url).rstrip("/")
        config = widget_runtime_config(service_origin=service_origin)
        if not config["enabled"]:
            return Response(
                "window.console && console.warn('ClarityOS widget is disabled for this deployment.');",
                media_type="application/javascript",
                status_code=404,
                headers={"Cache-Control": "no-store"},
            )
        payload = (
            f"window.__CLARITYOS_WIDGET_CONFIG__ = {json.dumps(config)};\n"
            f"{widget_script()}"
        )
        return Response(payload, media_type="application/javascript", headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return error_response(exc)


@app.get("/widget/config")
def widget_config(
    request: Request,
    origin: str | None = None,
):
    try:
        service_origin = str(request.base_url).rstrip("/")
        return widget_runtime_config(service_origin=service_origin, requested_origin=origin)
    except Exception as exc:
        return error_response(exc)


def workflow_run(payload: dict):
    user_input = payload.get("input", "")
    agent_name = payload.get("agent", "default")
    tool_name = payload.get("tool")
    tool_args = payload.get("tool_args")
    approval_id = payload.get("approval_id")

    return start_workflow(
        user_input=user_input,
        agent_name=agent_name,
        tool_name=tool_name,
        tool_args=tool_args,
        approval_id=approval_id,
    )


@app.post("/sessions")
def session_create(payload: dict | None = None):
    try:
        body = payload or {}
        return create_session(
            title=body.get("title"),
            agent=body.get("agent", "default"),
            metadata=body.get("metadata"),
            memory_scope=body.get("memory_scope"),
            surface=body.get("surface"),
        )
    except Exception as exc:
        return error_response(exc)


@app.get("/sessions")
def session_list(
    status: str | None = None,
    agent: str | None = None,
    limit: int | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return {
            "sessions": list_sessions(status=status, agent=agent, limit=limit),
        }
    except Exception as exc:
        return error_response(exc)


@app.get("/sessions/{session_id}")
def session_status(
    session_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return session_snapshot(load_session(session_id))
    except Exception as exc:
        return error_response(exc)


@app.get("/assistant/sessions/{session_id}")
def assistant_session_status(
    session_id: str,
    x_session_token: str | None = Header(default=None, alias=SESSION_AUTH_HEADER),
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        return session_snapshot(
            require_session_or_operator_auth(
                session_id,
                x_session_token,
                x_operator_token,
            )
        )
    except Exception as exc:
        return error_response(exc)


@app.get("/sessions/{session_id}/control")
def session_control(
    session_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return session_control_view(session_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/sessions/{session_id}/archive")
def session_archive(
    session_id: str,
    payload: dict | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        body = payload or {}
        return archive_session(session_id, reason=body.get("reason"))
    except Exception as exc:
        return error_response(exc)


@app.post("/sessions/{session_id}/continuity/compact")
def session_continuity_compact(
    session_id: str,
    payload: dict | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        body = payload or {}
        return compact_session_continuity(
            session_id,
            keep_recent_messages=body.get("keep_recent_messages", 6),
            memory_limit=body.get("memory_limit", 10),
            max_summary_chars=body.get("max_summary_chars", 1200),
        )
    except Exception as exc:
        return error_response(exc)


@app.post("/sessions/prune")
def session_prune(
    payload: dict | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        body = payload or {}
        return prune_sessions(
            statuses=body.get("statuses"),
            older_than_hours=body.get("older_than_hours", 168),
            limit=body.get("limit"),
        )
    except Exception as exc:
        return error_response(exc)


@app.post("/sessions/{session_id}/messages")
def session_append_message(
    session_id: str,
    payload: dict,
    x_session_token: str | None = Header(default=None, alias=SESSION_AUTH_HEADER),
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_session_or_operator_auth(session_id, x_session_token, x_operator_token)
        return append_message_to_session(
            session_id,
            content=payload.get("input", ""),
            agent=payload.get("agent"),
            tool_name=payload.get("tool"),
            tool_args=payload.get("tool_args"),
            approval_id=payload.get("approval_id"),
            metadata=payload.get("metadata"),
        )
    except Exception as exc:
        return error_response(exc)


def queue_job_request(payload: dict):
    job_type = payload.get("type", "workflow_start")
    workflow_id = payload.get("workflow_id")
    if job_type in {"workflow_resume", "workflow_subrun"} and not workflow_id:
        raise ValueError(f"Job type `{job_type}` requires `workflow_id`")

    job_payload = {
        "input": payload.get("input", ""),
        "agent": payload.get("agent", "default"),
        "tool": payload.get("tool"),
        "tool_args": payload.get("tool_args"),
        "approval_id": payload.get("approval_id"),
    }
    if workflow_id is not None:
        job_payload["workflow_id"] = workflow_id
    if job_type == "workflow_subrun":
        job_payload["role"] = payload.get("role")
        job_payload["allowed_capabilities"] = payload.get("allowed_capabilities")
        job_payload["allowed_tools"] = payload.get("allowed_tools")
        job_payload["task_intent"] = payload.get("task_intent")
        job_payload["expected_output"] = payload.get("expected_output")
        job_payload["completion_criteria"] = payload.get("completion_criteria")
        job_payload["shared_memory_ids"] = payload.get("shared_memory_ids")

    return create_job(
        job_type=job_type,
        payload=job_payload,
        priority=payload.get("priority", 100),
        delay_seconds=payload.get("delay_seconds", 0),
        run_at=payload.get("run_at"),
        workflow_id=workflow_id,
        parent_job_id=payload.get("parent_job_id"),
        idempotency_key=payload.get("idempotency_key"),
        max_attempts=payload.get("max_attempts", 1),
        retry_backoff_seconds=payload.get("retry_backoff_seconds", 30),
    )


@app.post("/workflows")
def workflow_start(payload: dict):
    try:
        return workflow_run(payload)
    except Exception as exc:
        return error_response(exc)


@app.post("/jobs")
def job_create(payload: dict):
    try:
        return queue_job_request(payload)
    except Exception as exc:
        return error_response(exc)


@app.post("/workers")
def worker_create(
    payload: dict,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return register_worker(
            name=payload.get("name"),
            lease_seconds=payload.get("lease_seconds", 30),
        )
    except Exception as exc:
        return error_response(exc)


@app.get("/workers")
def worker_list(
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return {
            "workers": list_workers(),
        }
    except Exception as exc:
        return error_response(exc)


@app.get("/workers/{worker_id}")
def worker_status(
    worker_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return load_worker(worker_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/workers/{worker_id}/heartbeat")
def worker_heartbeat(
    worker_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return heartbeat_worker(worker_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/workers/{worker_id}/jobs/claim")
def worker_claim_job(
    worker_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        job = claim_next_job(worker_id)
        return {"job": job}
    except Exception as exc:
        return error_response(exc)


@app.post("/workers/{worker_id}/jobs/{job_id}/run")
def worker_run_claimed_job(
    worker_id: str,
    job_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return run_claimed_job(worker_id, job_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/workers/{worker_id}/jobs/run-next")
def worker_run_next(
    worker_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return {"job": run_next_job(worker_id)}
    except Exception as exc:
        return error_response(exc)


@app.post("/workers/reclaim-expired")
def worker_reclaim_expired(
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return reclaim_expired_leases()
    except Exception as exc:
        return error_response(exc)


@app.get("/workers/health")
def workers_health(
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return worker_health_view()
    except Exception as exc:
        return error_response(exc)


@app.post("/workers/repair-orphans")
def worker_repair_orphans(
    payload: dict | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        body = payload or {}
        return repair_orphaned_workers(limit=body.get("limit"))
    except Exception as exc:
        return error_response(exc)


@app.post("/workers/{worker_id}/reset")
def worker_reset(
    worker_id: str,
    payload: dict | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        body = payload or {}
        return reset_worker(
            worker_id,
            reason=body.get("reason", "operator"),
            force=body.get("force", False),
            requeue_running_job=body.get("requeue_running_job", False),
        )
    except Exception as exc:
        return error_response(exc)


@app.get("/jobs")
def job_list(
    status: str | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return {
            "jobs": list_jobs(status=status),
        }
    except Exception as exc:
        return error_response(exc)


@app.get("/jobs/{job_id}")
def job_status(
    job_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return load_job(job_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/jobs/{job_id}/cancel")
def job_cancel(
    job_id: str,
    payload: dict | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        reason = "operator"
        if payload is not None:
            reason = payload.get("reason", "operator")
        return cancel_job_execution(job_id, reason=reason)
    except Exception as exc:
        return error_response(exc)


@app.post("/jobs/{job_id}/reschedule")
def job_reschedule(
    job_id: str,
    payload: dict | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        body = payload or {}
        return reschedule_job(
            job_id,
            delay_seconds=body.get("delay_seconds", 0),
            run_at=body.get("run_at"),
        )
    except Exception as exc:
        return error_response(exc)


@app.get("/queue")
def queue_status(
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return queue_summary()
    except Exception as exc:
        return error_response(exc)


@app.get("/queue/health")
def queue_health(
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return queue_health_view()
    except Exception as exc:
        return error_response(exc)


@app.post("/queue/promote-ready")
def queue_promote_ready(
    payload: dict | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        body = payload or {}
        return promote_due_jobs(limit=body.get("limit"))
    except Exception as exc:
        return error_response(exc)


@app.post("/queue/repair-stale")
def queue_repair_stale(
    payload: dict | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        body = payload or {}
        return repair_stale_job_state(limit=body.get("limit"))
    except Exception as exc:
        return error_response(exc)


@app.post("/queue/prune")
def queue_prune(
    payload: dict | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        body = payload or {}
        return prune_jobs(
            statuses=body.get("statuses"),
            older_than_seconds=body.get("older_than_seconds", 0),
            limit=body.get("limit"),
        )
    except Exception as exc:
        return error_response(exc)


@app.get("/approvals/{approval_id}")
def approval_status(
    approval_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return get_approval(approval_id)
    except Exception as exc:
        return error_response(exc)


@app.get("/artifacts/{artifact_id}")
def artifact_status(artifact_id: str):
    try:
        return load_artifact(artifact_id)
    except Exception as exc:
        return error_response(exc)


def parse_tags_param(tags: str | None) -> list[str] | None:
    if tags is None:
        return None
    parsed = [tag.strip() for tag in tags.split(",") if tag.strip()]
    return parsed or None


def persisted_state_registry(kind: str | None = None) -> dict[str, dict[str, object]] | dict[str, object]:
    registry = {
        "sessions": {"schema": SESSION_STATE_SCHEMA, "path": session_path, "directory": SESSION_DIR},
        "workflows": {"schema": WORKFLOW_STATE_SCHEMA, "path": workflow_path, "directory": WORKFLOW_DIR},
        "jobs": {"schema": JOB_STATE_SCHEMA, "path": job_path, "directory": JOB_DIR},
        "memories": {"schema": MEMORY_STATE_SCHEMA, "path": memory_path, "directory": MEMORY_DIR},
        "workers": {"schema": WORKER_STATE_SCHEMA, "path": worker_path, "directory": WORKER_DIR},
        "approvals": {"schema": APPROVAL_STATE_SCHEMA, "path": approval_path, "directory": APPROVAL_DIR},
        "artifacts": {"schema": ARTIFACT_STATE_SCHEMA, "path": artifact_path, "directory": ARTIFACT_DIR},
    }
    if kind is None:
        return registry
    if kind not in registry:
        raise ValueError(
            "State `kind` must be one of: sessions, workflows, jobs, memories, workers, approvals, artifacts"
        )
    return registry[kind]


def persisted_state_schemas() -> dict[str, dict[str, str]]:
    return {
        state_kind: {"schema": details["schema"]}
        for state_kind, details in persisted_state_registry().items()
    }


def persisted_state_locator(kind: str) -> tuple[str, callable]:
    details = persisted_state_registry(kind)
    return details["schema"], details["path"]


def persisted_state_directory(kind: str) -> tuple[str, object]:
    details = persisted_state_registry(kind)
    return details["schema"], details["directory"]


def normalize_state_kinds(value: object | None) -> list[str]:
    if value is None:
        return list(persisted_state_registry().keys())
    if not isinstance(value, list) or not value:
        raise ValueError("State migration `kinds` must be a non-empty list")

    normalized = []
    seen = set()
    for raw_kind in value:
        if not isinstance(raw_kind, str) or not raw_kind.strip():
            raise ValueError("State migration `kinds` must contain non-empty strings")
        kind = raw_kind.strip()
        persisted_state_registry(kind)
        if kind not in seen:
            normalized.append(kind)
            seen.add(kind)
    return normalized


@app.get("/state/schemas")
def state_schemas(
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return {
            "current_version": PERSISTED_STATE_VERSION,
            "schemas": persisted_state_schemas(),
        }
    except Exception as exc:
        return error_response(exc)


@app.get("/state/{kind}/{state_id}")
def state_inspect(
    kind: str,
    state_id: str,
    include_payload: bool = False,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        schema, locator = persisted_state_locator(kind)
        path = locator(state_id)
        if not path.is_file():
            raise FileNotFoundError(f"State not found: {kind}/{state_id}")
        return {
            "kind": kind,
            "state_id": state_id,
            **inspect_state_payload(path, schema=schema, include_payload=include_payload),
        }
    except Exception as exc:
        return error_response(exc)


@app.post("/state/{kind}/{state_id}/migrate")
def state_migrate(
    kind: str,
    state_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        schema, locator = persisted_state_locator(kind)
        path = locator(state_id)
        if not path.is_file():
            raise FileNotFoundError(f"State not found: {kind}/{state_id}")
        return {
            "kind": kind,
            "state_id": state_id,
            **migrate_state_payload(path, schema=schema),
        }
    except Exception as exc:
        return error_response(exc)


@app.post("/state/{kind}/migrate-all")
def state_migrate_all(
    kind: str,
    payload: dict | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        body = payload or {}
        schema, directory = persisted_state_directory(kind)
        return {
            "kind": kind,
            **migrate_state_directory(
                directory,
                schema=schema,
                limit=body.get("limit"),
                include_unchanged=body.get("include_unchanged", False),
            ),
        }
    except Exception as exc:
        return error_response(exc)


@app.post("/state/migrate")
def state_migrate_runtime(
    payload: dict | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        body = payload or {}
        kinds = normalize_state_kinds(body.get("kinds"))
        limit_per_kind = body.get("limit_per_kind")
        include_unchanged = body.get("include_unchanged", False)

        results = {}
        total_processed = 0
        total_migrated = 0
        total_unchanged = 0
        for kind in kinds:
            schema, directory = persisted_state_directory(kind)
            result = migrate_state_directory(
                directory,
                schema=schema,
                limit=limit_per_kind,
                include_unchanged=include_unchanged,
            )
            results[kind] = result
            total_processed += result["processed_count"]
            total_migrated += result["migrated_count"]
            total_unchanged += result["unchanged_count"]

        return {
            "kinds": kinds,
            "processed_count": total_processed,
            "migrated_count": total_migrated,
            "unchanged_count": total_unchanged,
            "results": results,
        }
    except Exception as exc:
        return error_response(exc)


@app.get("/memories")
def memory_list(
    memory_type: str | None = None,
    scope_kind: str | None = None,
    agent: str | None = None,
    workflow_id: str | None = None,
    run_id: str | None = None,
    tags: str | None = None,
    limit: int | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return {
            "memories": list_memories(
                memory_type=memory_type,
                scope_kind=scope_kind,
                agent=agent,
                workflow_id=workflow_id,
                run_id=run_id,
                tags=parse_tags_param(tags),
                limit=limit,
            ),
        }
    except Exception as exc:
        return error_response(exc)


@app.get("/memories/{memory_id}")
def memory_status(
    memory_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return load_memory(memory_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/memories/{memory_id}/delete")
def memory_delete(
    memory_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return delete_memory(memory_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/approvals/{approval_id}/approve")
def approval_approve(
    approval_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return approve_approval(approval_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/approvals/{approval_id}/deny")
def approval_deny(
    approval_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return deny_approval(approval_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/approvals/{approval_id}/abort")
def approval_abort(
    approval_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return abort_approval(approval_id)
    except Exception as exc:
        return error_response(exc)


@app.get("/workflows/{workflow_id}")
def workflow_status(
    workflow_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return workflow_control_view(workflow_id)
    except Exception as exc:
        return error_response(exc)


@app.get("/incidents/workflows/{workflow_id}")
def workflow_incident(
    workflow_id: str,
    trace_limit: int = 20,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return workflow_incident_view(workflow_id, trace_limit=trace_limit)
    except Exception as exc:
        return error_response(exc)


@app.get("/incidents/workflows/{workflow_id}/summary")
def workflow_incident_summary(
    workflow_id: str,
    trace_limit: int = 20,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return workflow_incident_summary_view(workflow_id, trace_limit=trace_limit)
    except Exception as exc:
        return error_response(exc)


@app.post("/workflows/{workflow_id}/resume")
def workflow_resume(
    workflow_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return resume_workflow(workflow_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/workflows/{workflow_id}/resume-safe")
def workflow_resume_safe(
    workflow_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return safe_resume_workflow(workflow_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/workflows/{workflow_id}/replay")
def workflow_replay(
    workflow_id: str,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return replay_workflow(workflow_id)
    except Exception as exc:
        return error_response(exc)


@app.post("/workflows/{workflow_id}/recover")
def workflow_recover(
    workflow_id: str,
    payload: dict | None = None,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        body = payload or {}
        return recover_workflow(
            workflow_id,
            reclaim_expired_jobs=body.get("reclaim_expired_jobs", False),
            reschedule_failed_jobs=body.get("reschedule_failed_jobs", False),
            reschedule_dead_letter_jobs=body.get("reschedule_dead_letter_jobs", False),
            limit=body.get("limit"),
        )
    except Exception as exc:
        return error_response(exc)


@app.post("/workflows/{workflow_id}/subruns")
def workflow_spawn_subrun(
    workflow_id: str,
    payload: dict,
    x_operator_token: str | None = Header(default=None, alias=OPERATOR_AUTH_HEADER),
):
    try:
        require_operator_auth(x_operator_token)
        return start_child_workflow(
            workflow_id,
            user_input=payload.get("input", ""),
            agent_name=payload.get("agent", "default"),
            tool_name=payload.get("tool"),
            tool_args=payload.get("tool_args"),
            role=payload.get("role"),
            allowed_capabilities=payload.get("allowed_capabilities"),
            allowed_tools=payload.get("allowed_tools"),
            task_intent=payload.get("task_intent"),
            expected_output=payload.get("expected_output"),
            completion_criteria=payload.get("completion_criteria"),
            shared_memory_ids=payload.get("shared_memory_ids"),
        )
    except Exception as exc:
        return error_response(exc)
