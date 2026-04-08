# Workflow Recovery Playbook

## Use When

- a workflow is `failed`
- a workflow is waiting on retry or approval and should be resumed safely
- child/job state drifted and the workflow needs operator-assisted recovery

## Pre-Checks

1. Inspect `GET /workflows/{workflow_id}`.
2. Inspect `GET /incidents/workflows/{workflow_id}` or `/summary`.
3. Identify the current blocker, first failure, and latest recovery attempt.

## Procedure

1. Use `POST /workflows/{workflow_id}/recover` to reclaim expired jobs or reschedule failed/dead-letter jobs.
2. Use `POST /workflows/{workflow_id}/resume-safe` for retry-wait or other resumable waiting states.
3. Use `POST /workflows/{workflow_id}/replay` only when the workflow should be re-executed from a failed state.

## Guardrails

- prefer `resume-safe` over replay when the workflow is already waiting in a recoverable state
- inspect related jobs and worker state before replaying high-impact workflows
