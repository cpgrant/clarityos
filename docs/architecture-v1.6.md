# ClarityClaw Runtime Architecture v1.6

This document describes the released runtime architecture for `v1.6`.

Scope:

- assistant browser surface
- embeddable widget surface
- operator control plane
- runtime orchestration
- session continuity and bounded carry-forward
- bounded child-workflow delegation and supervision
- queue and worker execution
- persisted state on local disk
- external model providers

## Summary

ClarityClaw `v1.6` remains a thin FastAPI service over an explicit runtime. The API layer exposes assistant, widget, operator, session, workflow, job, worker, memory, approval, and state endpoints in [`api/main.py`](../api/main.py). Most behavior is implemented in runtime modules rather than in route handlers.

Compared with the earlier `v1.4` snapshot, the released `v1.6` shape is still container-light, but it now makes two important quality layers explicit in runtime state rather than leaving them implicit in prompts:

- session continuity summaries, compaction metadata, and bounded carry-forward in [`runtime/session.py`](../runtime/session.py)
- bounded child delegation contracts, child-result synthesis, and delegated-run auditability in [`runtime/workflow_runner.py`](../runtime/workflow_runner.py), [`runtime/workflow.py`](../runtime/workflow.py), and [`runtime/control_plane.py`](../runtime/control_plane.py)

The runtime centers on:

- session-backed assistant interactions and continuity state in [`runtime/session.py`](../runtime/session.py)
- workflow, child-workflow, and delegation execution in [`runtime/workflow_runner.py`](../runtime/workflow_runner.py)
- workflow state persistence and lineage metadata in [`runtime/workflow.py`](../runtime/workflow.py)
- agent execution, policy checks, prompt building, and tracing in [`runtime/agent.py`](../runtime/agent.py)
- queue and worker coordination in [`runtime/queue.py`](../runtime/queue.py) and [`runtime/worker.py`](../runtime/worker.py)
- operator, continuity, workflow-control, and incident views in [`runtime/control_plane.py`](../runtime/control_plane.py)

Persisted JSON state under `sessions/`, `workflows/`, `jobs/`, `workers/`, `memories/`, `approvals/`, and `artifacts/` remains the system of record for runtime state.

Mermaid sources for the diagrams in this document live in `docs/diagrams/`.

## Container View

Source:

- [`docs/diagrams/architecture-v1.6.mmd`](./diagrams/architecture-v1.6.mmd)

## System Context View

This view shows ClarityClaw as a deployed system in relation to assistant users, host sites, operators, and model providers.

Source:

- [`docs/diagrams/system-context-v1.6.mmd`](./diagrams/system-context-v1.6.mmd)

## Assistant Message Flow

This is the main synchronous browser-first path for `/assistant` and the iframe-backed widget, including continuity loading and bounded carry-forward.

Source:

- [`docs/diagrams/assistant-message-flow-v1.6.mmd`](./diagrams/assistant-message-flow-v1.6.mmd)

## Background Job Flow

This is the asynchronous path for queued starts, resumes, and bounded child subruns with explicit delegation contracts.

Source:

- [`docs/diagrams/background-job-flow-v1.6.mmd`](./diagrams/background-job-flow-v1.6.mmd)

## Runtime State Lifecycle View

This view summarizes the released `v1.6` state transitions for sessions, workflows, jobs, workers, continuity state, and delegated-work quality state.

Source:

- [`docs/diagrams/runtime-state-lifecycle-v1.6.mmd`](./diagrams/runtime-state-lifecycle-v1.6.mmd)

## State Domains

| Path | Purpose |
| --- | --- |
| `config/` | Agent, model, and policy configuration loaded at runtime |
| `sessions/` | Session ownership, message history, continuity summaries, and workflow linkage |
| `workflows/` | Workflow state, lineage, delegation contracts, child synthesis, and audit metadata |
| `jobs/` | Queued, scheduled, running, failed, and completed job state |
| `workers/` | Worker leases, assignments, and transition history |
| `memories/` | Typed memory records, workflow-linked summaries, and continuity support state |
| `approvals/` | Approval requests and resume state |
| `artifacts/` | Runtime artifacts produced by workflows and tools |
| `logs/` | Trace, incident-correlation, and operator-facing operational log output |

## Key Boundaries

- The FastAPI layer is intentionally thin. Route handlers mostly validate auth, unpack payloads, and delegate to runtime modules.
- Continuity and multi-agent quality are explicit state concerns, not hidden prompt-only behavior. Session compaction, continuity summaries, child delegation contracts, synthesis, and audit state are all visible in persisted records.
- The queue is local-state-backed, not an external broker. `jobs/` and `workers/` together still capture scheduling, leasing, retry, reclaim, and background execution behavior.
- Parent and child workflows stay policy-bounded. Delegated work inherits explicit capability and tool constraints rather than introducing a separate autonomy layer.
- Operator views are part of the same runtime. The control plane reads the same persisted state used by assistant execution rather than maintaining a separate monitoring store.
- The model provider is still an external dependency boundary. The runtime can target OpenAI-backed agents or a local Ollama server.

## Main Surfaces And Entry Points

- `/assistant`, `/widget`, `/widget.js`, and `/operator` are served in [`api/main.py`](../api/main.py).
- Session-backed assistant work and continuity handling start in [`runtime/session.py`](../runtime/session.py).
- Workflow execution and bounded child delegation start in [`runtime/workflow_runner.py`](../runtime/workflow_runner.py).
- Workflow state and lineage persistence live in [`runtime/workflow.py`](../runtime/workflow.py).
- Agent execution, policy evaluation, tool dispatch, and tracing live in [`runtime/agent.py`](../runtime/agent.py).
- Queue and worker execution live in [`runtime/queue.py`](../runtime/queue.py) and [`runtime/worker.py`](../runtime/worker.py).
- Operator inspection, child-result synthesis, continuity views, and incident recovery views live in [`runtime/control_plane.py`](../runtime/control_plane.py).

## Notes For Future Versions

`v1.7` work is expected to deepen deployment and operator maturity without changing the high-level runtime ownership boundaries. If `v1.7` introduces a materially new deployment boundary or packaging subsystem, add `docs/architecture-v1.7.md` rather than rewriting this released snapshot in place.
