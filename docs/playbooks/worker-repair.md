# Worker Repair Playbook

## Use When

- workers are stuck `busy`
- leases expired without queue state converging
- orphaned workers still point at no-longer-running jobs

## Pre-Checks

1. Inspect `GET /workers/health`.
2. Inspect `GET /queue/health`.
3. Confirm whether the affected jobs should be requeued or simply released.

## Procedure

1. Repair orphaned workers with `POST /workers/repair-orphans`.
2. For a specific stuck worker, call `POST /workers/{worker_id}/reset`.
3. If needed, reclaim expired leases with `POST /workers/reclaim-expired`.

## Guardrails

- use `requeue_running_job` only when re-execution is acceptable
- record the reason for resets so incident timelines stay meaningful
