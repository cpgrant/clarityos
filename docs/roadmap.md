# ClarityOS Roadmap

This document is the detailed milestone plan for ClarityOS.

Update this file first when milestone scope changes, then keep the summary in the repository root `README.md` aligned with it.

## Current Status

- Latest completed milestone: `v1.1`
- Next planned milestone: `v1.2`
- Next planned slice: `v1.2` slice 1 session ownership and surface auth

## Milestones

1. `v0.1` - execution
Status: completed

2. `v0.2` - traceability
Status: completed

3. `v0.2.1` - lightweight testing
Status: completed

4. `v0.2.2` - multi-provider support
Status: completed

5. `v0.3` - explicit tools
Status: completed

6. `v0.4` - control and safety
Status: completed

7. `v0.5` - workflows and control plane
Status: completed

8. `v0.6` - queues and jobs
Status: completed

9. `v0.7` - memory and retrieval
Status: completed

Goal:
Add explicit, typed memory and bounded retrieval without breaking the runtime's inspectability.

Slices:

- Slice 1: typed memory layers - completed
- Slice 2: bounded retrieval - completed
- Slice 3: agent integration - completed
- Slice 4: workflow memory lifecycle - completed
- Slice 5: retrieval safety and operator controls - completed

Acceptance criteria:

- Typed memory records exist with explicit schemas such as `fact`, `summary`, `observation`, and `artifact_ref`.
- Durable memory storage supports create, read, list, and bounded query operations.
- `memory_read` and `memory_write` are enforced through the existing policy layer.
- Retrieval is bounded by explicit limits and returns source metadata instead of silently dumping full memory state into prompts.
- Memory activity appears in traces and the workflow control plane.
- Automated tests cover memory CRUD, bounded retrieval, policy denial, and workflow integration.

10. `v0.8` - multi-agent coordination
Status: completed

Goal:
Coordinate multiple agents through explicit workflows, bounded delegation, and scoped memory access.

Slices:

- Slice 1: bounded delegation foundations - completed
- Slice 2: child workflow execution and lineage - completed
- Slice 3: scoped shared memory handoff - completed
- Slice 4: operator inspection and failure isolation - completed

Acceptance criteria:

- Workflows can coordinate bounded child agents with explicit lineage and role assignment.
- Agent delegation respects configurable limits for depth, fan-out, and allowed capabilities.
- Agents can read shared memory selectively and write scoped memory intentionally.
- Multi-agent execution is inspectable through traces, workflow state, and control-plane views.
- Failures in one child workflow do not silently corrupt sibling or parent workflow state.
- Automated tests cover delegation, lineage, scoped memory access, and failure isolation.

11. `v0.9` - production hardening
Status: completed

Goal:
Prepare the runtime for sustained production operation with recovery, governance, and operational visibility.

Slices:

- Slice 1: state versioning and migrations - completed
- Slice 2: operator recovery and pruning controls - completed
- Slice 3: observability and incident debugging - completed
- Slice 4: auth, deployment, and resilience hardening - completed

Acceptance criteria:

- Durable state formats are versioned and have a clear migration path.
- Operators can inspect, replay, prune, and recover workflows, jobs, artifacts, and memory safely.
- Auth, access control, retention, and audit expectations are defined for production deployment.
- Queue, worker, memory, and workflow subsystems expose enough observability for incident debugging.
- System behavior under retry, reclaim, restart, and partial-failure conditions is documented and tested.
- Production hardening includes load, soak, and recovery validation beyond the minimal unit suite.

12. `v1.0` - release readiness and first production profile
Status: completed

Goal:
Translate the hardened runtime into a repeatable, supportable production profile with explicit rollout defaults, operational playbooks, and a narrow first live use case.

Slices:

- Slice 1: soak, load, and recovery validation - completed
- Slice 2: rollout defaults and deployment profile - completed
- Slice 3: operator governance and maintenance playbooks - completed
- Slice 4: first production path and release criteria - completed

Acceptance criteria:

- Soak, restart, reclaim, retry, and failure-recovery drills are repeatable and documented beyond the unit suite.
- A production deployment profile exists with explicit env defaults, policy posture, retention guidance, and operator expectations.
- Operators have documented playbooks for incident response, safe maintenance, migration, recovery, and pruning.
- The first production use case is intentionally narrow, measurable, and supported by release gates rather than informal judgment.

First production use case:

- single-tenant, self-hosted, API-first workflow runtime
- bounded assistant and researcher-style tasks started through workflow and job APIs
- operator-managed recovery, replay, prune, and inspection flows
- no chat surface, plugin marketplace, or many-channel product scope yet

Release gates:

- targeted trusted-runtime drills pass
- full unit suite passes
- production env, operator auth, and explicit config selection are in place
- operator profile confirms the intended runtime posture
- queue and worker health start clean on release candidates
- documented playbooks map directly to real operator endpoints

13. `v1.1` - first assistant surface and session gateway
Status: completed

Goal:
Deliver the first real “OpenClaw-ish” use case on top of the hardened runtime: one assistant surface, one explicit session model, and one thin operator-facing UI, while preserving ClarityOS’s stronger guarantees and bounded execution model.

Slices:

- Slice 1: session and conversation model - completed
- Slice 2: first assistant surface - completed
- Slice 3: operator UI and conversation inspection - completed
- Slice 4: first external channel or gateway adapter - completed

Acceptance criteria:

- The runtime supports explicit conversation/session records that map inbound user interactions to workflows, memory scope, and operator-visible history.
- A first assistant surface exists, ideally web-first, that can send user messages into the runtime and receive async workflow-backed responses.
- Operators can inspect sessions, related workflows, incidents, and recovery actions through a simple UI rather than API-only access.
- Channel integration remains thin: surface adapters hand work to the existing workflow, queue, memory, and control-plane layers rather than duplicating runtime logic.
- The shipped use case is intentionally narrow and reliable, with one strong surface before broader channel expansion.

Chosen first adapter:

- embeddable web widget loaded through `/widget.js` and rendered by `/widget`
- browser-only, same-runtime, and self-hosted
- explicitly not Telegram, Slack, or broad multi-channel routing at this stage

14. `v1.2` - assistant deployment hardening
Status: planned

Goal:
Turn the new assistant-facing surfaces into a narrowly deployable assistant profile with explicit auth, embed posture, and operator support boundaries.

Slices:

- Slice 1: session ownership and surface auth - planned
- Slice 2: embed policy and branded deployment profile - planned
- Slice 3: assistant operator playbooks and maintenance flows - planned
- Slice 4: first assistant deployment path and release criteria - planned

Acceptance criteria:

- Assistant and operator surfaces have explicit auth and session-ownership expectations rather than relying on development-only posture.
- Embed origins, branding defaults, and surface configuration are documented and adjustable without code changes.
- Operators have playbooks for assistant-surface incidents, recovery, pruning, and deployment maintenance.
- One narrow assistant deployment path is measurable, supportable, and clearly in scope before broader surface expansion.
