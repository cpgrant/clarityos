import hmac
import os

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse

from runtime.agent import AGENTS_CONFIG_ENV_VAR, agents_config_path
from runtime.artifact import ARTIFACT_DIR, ARTIFACT_STATE_SCHEMA, artifact_path, load_artifact
from runtime.approval import APPROVAL_DIR, APPROVAL_STATE_SCHEMA, abort_approval, approval_path, approve_approval, deny_approval, get_approval
from runtime.control_plane import (
    queue_health_view,
    recover_workflow,
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

app = FastAPI(title="ClarityOS", version="1.0.0")
OPERATOR_TOKEN_ENV_VAR = "CLARITYOS_OPERATOR_TOKEN"
OPERATOR_AUTH_HEADER = "X-Operator-Token"


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


def error_status_code(exc: Exception) -> int:
    if isinstance(exc, FileNotFoundError):
        return 404
    if isinstance(exc, OperatorAuthError):
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


def operator_auth_enabled() -> bool:
    token = os.getenv(OPERATOR_TOKEN_ENV_VAR)
    return isinstance(token, str) and bool(token.strip())


def operator_auth_status() -> dict[str, object]:
    return {
        "enabled": operator_auth_enabled(),
        "header": OPERATOR_AUTH_HEADER,
        "env_var": OPERATOR_TOKEN_ENV_VAR,
    }


def operator_profile_status() -> dict[str, object]:
    return {
        "environment": {
            "name": runtime_environment(),
            "production_mode": production_mode_enabled(),
        },
        "operator_auth": operator_auth_status(),
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
        },
        "state": {
            "current_version": PERSISTED_STATE_VERSION,
            "directories": {
                "workflows": str(WORKFLOW_DIR),
                "jobs": str(JOB_DIR),
                "workers": str(WORKER_DIR),
                "memories": str(MEMORY_DIR),
                "artifacts": str(ARTIFACT_DIR),
                "approvals": str(APPROVAL_DIR),
            },
        },
    }


def require_operator_auth(operator_token: str | None) -> None:
    configured = os.getenv(OPERATOR_TOKEN_ENV_VAR)
    if not isinstance(configured, str) or not configured.strip():
        return
    candidate = operator_token if isinstance(operator_token, str) else ""
    if not hmac.compare_digest(candidate, configured):
        raise OperatorAuthError(
            f"Operator token is required via `{OPERATOR_AUTH_HEADER}`",
            header_name=OPERATOR_AUTH_HEADER,
        )


@app.post("/run")
def run(payload: dict):
    try:
        return workflow_run(payload)
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
            "State `kind` must be one of: workflows, jobs, memories, workers, approvals, artifacts"
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
            shared_memory_ids=payload.get("shared_memory_ids"),
        )
    except Exception as exc:
        return error_response(exc)
