# Assistant Surface Incident Playbook

## Use When

- the web assistant or widget starts returning session-token errors
- a user reports a stuck session, missing reply, or repeated waiting state
- operators need to inspect one assistant-facing session without bypassing the runtime model

## Pre-Checks

1. Check `GET /operator/profile` to confirm environment, session-auth posture, and widget posture.
2. Inspect the session with `GET /sessions/{session_id}/control`.
3. If the issue is workflow-related, inspect `latest_incident_path` from the session control view.

## Procedure

1. Confirm the session surface and auth posture from:
   - `ownership`
   - `maintenance`
   - `actions`
2. If the session is blocked on workflow state, prefer runtime recovery first:
   - safe resume
   - workflow recover
   - replay only if recovery is not appropriate
3. If the session itself should stop accepting user input, archive it with:
   - `POST /sessions/{session_id}/archive`
4. If the issue is browser-side auth loss, have the client create a fresh session rather than manually editing persisted state.

## Guardrails

- do not edit session JSON by hand unless you are performing offline forensics
- do not use operator-token access as a substitute for fixing session-token/browser behavior
- archive broken assistant sessions before pruning them
