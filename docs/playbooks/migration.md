# Migration Playbook

## Use When

- a runtime upgrade introduces a persisted-state schema change
- operator inspection shows legacy state that should be rewritten in place

## Pre-Checks

1. Back up `workflows/`, `jobs/`, `workers/`, `memories/`, `artifacts/`, and `approvals/`.
2. Verify `GET /operator/profile`.
3. Inspect representative records with `GET /state/{kind}/{state_id}`.

## Procedure

1. Migrate a single record first with `POST /state/{kind}/{state_id}/migrate`.
2. Re-inspect that record with `GET /state/{kind}/{state_id}`.
3. Migrate one full state kind with `POST /state/{kind}/migrate-all`.
4. Use `POST /state/migrate` only after per-kind migration behaves as expected.

## Exit Criteria

- migrated records report `legacy_format: false`
- no unsupported schema/version errors remain for the targeted state kind
