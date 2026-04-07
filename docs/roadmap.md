# ClarityOS Roadmap

This document is the detailed milestone plan for ClarityOS.

Update this file first when milestone scope changes, then keep the summary in the repository root `README.md` aligned with it.

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
Status: planned

Goal:
Add explicit, typed memory and bounded retrieval without breaking the runtime's inspectability.

Slices:

- Slice 1: typed memory layers
- Slice 2: bounded retrieval
- Slice 3: agent integration
- Slice 4: workflow memory lifecycle
- Slice 5: retrieval safety and operator controls

Acceptance criteria:

- Typed memory records exist with explicit schemas such as `fact`, `summary`, `observation`, and `artifact_ref`.
- Durable memory storage supports create, read, list, and bounded query operations.
- `memory_read` and `memory_write` are enforced through the existing policy layer.
- Retrieval is bounded by explicit limits and returns source metadata instead of silently dumping full memory state into prompts.
- Memory activity appears in traces and the workflow control plane.
- Automated tests cover memory CRUD, bounded retrieval, policy denial, and workflow integration.

10. `v0.8` - multi-agent coordination
Status: planned

Goal:
Coordinate multiple agents through explicit workflows, bounded delegation, and scoped memory access.

Acceptance criteria:

- Workflows can coordinate bounded child agents with explicit lineage and role assignment.
- Agent delegation respects configurable limits for depth, fan-out, and allowed capabilities.
- Agents can read shared memory selectively and write scoped memory intentionally.
- Multi-agent execution is inspectable through traces, workflow state, and control-plane views.
- Failures in one child workflow do not silently corrupt sibling or parent workflow state.
- Automated tests cover delegation, lineage, scoped memory access, and failure isolation.

11. `v0.9` - production hardening
Status: planned

Goal:
Prepare the runtime for sustained production operation with recovery, governance, and operational visibility.

Acceptance criteria:

- Durable state formats are versioned and have a clear migration path.
- Operators can inspect, replay, prune, and recover workflows, jobs, artifacts, and memory safely.
- Auth, access control, retention, and audit expectations are defined for production deployment.
- Queue, worker, memory, and workflow subsystems expose enough observability for incident debugging.
- System behavior under retry, reclaim, restart, and partial-failure conditions is documented and tested.
- Production hardening includes load, soak, and recovery validation beyond the minimal unit suite.
