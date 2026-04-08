# Session Cleanup Playbook

## Use When

- archived assistant sessions are accumulating
- recovered or errored sessions need a retention-oriented cleanup pass
- operators need a safe session maintenance workflow that does not bypass workflow recovery

## Pre-Checks

1. Inspect `GET /sessions/{session_id}/control` for any session you plan to archive.
2. Confirm `maintenance.recommendation` and whether the session is still linked to active workflow work.
3. Verify the target sessions are in a cleanup-safe status:
   - `archived`
   - `errored`
   - `recovered`

## Procedure

1. Archive an individual session when it should stop taking input:
   - `POST /sessions/{session_id}/archive`
2. Re-check the control view to confirm the session is now `archived`.
3. Prune old archived session state in small batches:
   - `POST /sessions/prune`
4. Start with narrow filters such as:
   - `statuses=["archived"]`
   - small `limit`
   - explicit `older_than_hours`

## Guardrails

- do not prune active or waiting sessions
- archive first when the status is `errored` or `recovered`
- preserve session ids associated with open incidents until after the incident review is complete
