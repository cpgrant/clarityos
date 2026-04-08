# Queue Cleanup Playbook

## Use When

- dead-letter or failed queue state is piling up
- stale scheduled or terminal jobs need operator cleanup

## Pre-Checks

1. Inspect `GET /queue/health`.
2. Inspect affected workflows with `GET /incidents/workflows/{workflow_id}/summary`.
3. Confirm the targeted jobs are terminal or explicitly safe to repair.

## Procedure

1. Repair stale queue state with `POST /queue/repair-stale`.
2. Re-check `GET /queue/health`.
3. Prune old terminal state with `POST /queue/prune`.

## Guardrails

- do not prune non-terminal jobs
- take a backup before large cleanup runs
- prefer small limits first, then widen if results are correct
