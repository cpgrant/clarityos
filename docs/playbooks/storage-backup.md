# Storage And Backup Playbook

## Use When

- preparing a packaged or deployed ClarityClaw environment for repeatable operation
- verifying which persisted directories must survive restart, upgrade, or host replacement
- planning backup and restore posture for a self-hosted deployment

## Pre-Checks

1. Inspect `GET /operator/profile`.
2. Confirm the configured storage root in `state.root`.
3. Review `state.guidance.must_preserve`, `state.guidance.should_preserve`, and `state.guidance.can_regenerate`.

## Expected State Layout

When `CLARITYCLAW_STATE_ROOT` is set, the supported packaged layout is:

- `sessions/`
- `workflows/`
- `jobs/`
- `workers/`
- `memories/`
- `artifacts/`
- `approvals/`
- `logs/`

## Backup Guidance

Treat these as critical and preserve them before maintenance, migration, or host replacement:

- `sessions/`
- `workflows/`
- `jobs/`
- `workers/`
- `memories/`

Treat these as recommended to preserve:

- `artifacts/`
- `approvals/`
- `logs/`

`logs/` can be regenerated over time, but backing them up is still useful for incident review and audits.

## Restore Guidance

1. Restore the full state-root tree when possible.
2. If only a subset can be restored, restore the critical directories first.
3. After restore, inspect `GET /operator/profile`, `GET /queue/health`, and `GET /workers/health`.
4. Use the existing workflow, queue, and worker repair playbooks if restored state shows drift.

## Exit Criteria

- operators can name the current state root and its persisted subdirectories
- backup posture is documented outside private setup knowledge
- the packaged deployment can be restarted without losing required state
