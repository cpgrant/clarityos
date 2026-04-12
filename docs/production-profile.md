# Production Profile

This document defines the current `v1.0` trusted-runtime deployment posture for ClarityClaw.

## Goal

Ship one narrow, supportable runtime profile with explicit safety, recovery, and operator expectations.

The associated first production use case and release gates live in `docs/v1.0-release-path.md`.

## Runtime Posture

- Set `CLARITYOS_ENV=production`.
- Set `CLARITYOS_OPERATOR_TOKEN` and terminate TLS in front of the API.
- Keep agent policy overrides disabled unless there is a reviewed exception.
- Treat `workflows/`, `jobs/`, `workers/`, `memories/`, `artifacts/`, `approvals/`, and `logs/` as operational state, not source files.

## Config Selection

ClarityClaw now supports env-selected config files so production defaults do not have to overwrite local development files.

- `CLARITYOS_AGENTS_CONFIG`
- `CLARITYOS_POLICIES_CONFIG`
- `CLARITYOS_MODELS_CONFIG`

Recommended production example:

```bash
export CLARITYOS_ENV=production
export CLARITYOS_OPERATOR_TOKEN=replace_me
export CLARITYOS_AGENTS_CONFIG=config/agents.production.yaml
export CLARITYOS_POLICIES_CONFIG=config/policies.production.yaml
```

The shipped production examples intentionally:

- reduce default step, tool, token, and wall-clock budgets
- disable delegation for the default agent
- keep `exec`, `http`, and `file_write` out of the default production posture
- keep memory access isolated to the dedicated memory operator

## Rollout Defaults

- Run `scripts/run_release_validation.sh` before any release candidate.
- Use the default API process behind a front proxy with TLS termination and request logging.
- Back up persisted state directories before migration or prune actions.
- Keep destructive maintenance operator-driven and explicit.

## Retention Guidance

Retention is still operator-managed.

- Prune terminal queue state intentionally with `/queue/prune`.
- Migrate persisted state intentionally with `/state/.../migrate` endpoints.
- Archive logs and persisted state outside the runtime before destructive cleanup.

## Operator Checks

Before a rollout, verify:

1. `GET /operator/auth`
2. `GET /operator/profile`
3. `GET /queue/health`
4. `GET /workers/health`

During recovery or maintenance, use the playbooks in `docs/playbooks/`.

## Out Of Scope

The `v1.0` production profile does not yet include:

- multi-region deployment
- automatic retention services
- a hosted control UI
- multi-channel assistant surfaces
- plugin or skill marketplace behavior
