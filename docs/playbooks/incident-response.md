# Incident Response Playbook

## Use When

- queue or worker health degrades
- a workflow fails unexpectedly
- operators need to understand cause and safe next action

## Procedure

1. Check `GET /operator/profile` to confirm environment and config posture.
2. Check `GET /queue/health` and `GET /workers/health`.
3. Open `GET /incidents/workflows/{workflow_id}` for the affected workflow.
4. Review:
   - `current_blocker`
   - `first_failure`
   - `latest_failure`
   - `latest_recovery_attempt`
   - `causality_chain`
5. Choose the least-destructive recovery:
   - repair stale queue or worker state
   - recover the workflow
   - resume safely
   - replay only if recovery and safe resume are not appropriate

## Aftercare

- capture the failing workflow id and related job/worker ids
- note whether the issue was policy, budget, runtime, or operator-state related
- preserve logs and state before destructive cleanup
