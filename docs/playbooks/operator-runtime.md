# Operator Runtime Posture

Use this playbook when the operator dashboard shows a runtime-posture recommendation that is not `within_runtime_bounds`.

Primary surfaces:

- `GET /operator/dashboard`
- `GET /operator/profile`
- `GET /queue/health`
- `GET /workers/health`

## What The Runtime Posture Card Means

The runtime-posture card is the bounded summary for repeated self-hosted operation.

It combines:

- session backlog and errored-session counts
- queue retry, failure, and expired-running-job signals
- worker expiration and orphaned-worker signals
- storage-root and backup-priority posture for packaged deployment

The card is meant to answer one question quickly:

`Can this runtime be left alone, or does an operator need to intervene now?`

## Recommendations

### `within_runtime_bounds`

- The packaged runtime is healthy enough for normal operation.
- Keep monitoring through the dashboard and normal release-validation flows.

### `monitor_runtime`

- Review waiting sessions, retry backlog, or expired worker leases.
- Open `/operator/dashboard`, `/queue/health`, and `/workers/health`.
- If the counts continue growing, move into queue cleanup or worker repair.

### `review_failures`

- Review errored sessions, failed jobs, or dead-letter jobs.
- Use the dashboard to identify affected sessions, then inspect related workflows and incidents.
- Use `queue-cleanup.md`, `workflow-recovery.md`, or `incident-response.md` as needed.

### `repair_worker_state`

- Worker/job ownership drift is present.
- Review `/queue/health` and `/workers/health` first.
- Reconcile expired running jobs, orphaned workers, or lease drift before treating the runtime as stable again.
- Follow `worker-repair.md` and `queue-cleanup.md` if manual repair is needed.

## Storage Notes

The runtime-posture card also reminds operators of packaged storage posture:

- the configured state root
- whether `CLARITYCLAW_STATE_ROOT` is set explicitly
- how many directories are critical, recommended, or regenerable

If the runtime is being run in a packaged deployment without an explicit state root, fix that before calling the deployment repeatable.
