# ClarityClaw Runtime Architecture v1.4

This document describes the released runtime architecture for `v1.4`.

Scope:

- assistant browser surface
- embeddable widget surface
- operator control plane
- runtime orchestration
- queue and worker execution
- persisted state on local disk
- external model providers

## Summary

ClarityClaw is a thin FastAPI service over an explicit runtime. The API layer exposes assistant, widget, operator, session, workflow, job, worker, memory, approval, and state endpoints in [`api/main.py`](../api/main.py). Most behavior is implemented in runtime modules rather than in route handlers.

The runtime centers on:

- session-backed assistant interactions in [`runtime/session.py`](../runtime/session.py)
- workflow and child-workflow execution in [`runtime/workflow_runner.py`](../runtime/workflow_runner.py)
- agent execution, policy checks, prompt building, and tracing in [`runtime/agent.py`](../runtime/agent.py)
- queue and worker coordination in [`runtime/queue.py`](../runtime/queue.py) and [`runtime/worker.py`](../runtime/worker.py)
- operator and incident views in [`runtime/control_plane.py`](../runtime/control_plane.py)

Persisted JSON state under `sessions/`, `workflows/`, `jobs/`, `workers/`, `memories/`, `approvals/`, and `artifacts/` is the system of record for runtime state.

Mermaid sources for the diagrams in this document live in `docs/diagrams/`.

## Container View

Source:

- [`docs/diagrams/architecture-v1.4.mmd`](./diagrams/architecture-v1.4.mmd)

## System Context View

This view shows ClarityClaw as a deployed system in relation to its users, host sites, operators, and model providers.

Source:

- [`docs/diagrams/system-context-v1.4.mmd`](./diagrams/system-context-v1.4.mmd)

## Assistant Message Flow

This is the main synchronous browser-first path for `/assistant` and the iframe-backed widget.

Source:

- [`docs/diagrams/assistant-message-flow-v1.4.mmd`](./diagrams/assistant-message-flow-v1.4.mmd)

## Background Job Flow

This is the asynchronous path for queued starts, resumes, and subruns.

Source:

- [`docs/diagrams/background-job-flow-v1.4.mmd`](./diagrams/background-job-flow-v1.4.mmd)

## Runtime State Lifecycle View

This view summarizes the released `v1.4` state transitions for sessions, workflows, jobs, and workers.

Source:

- [`docs/diagrams/runtime-state-lifecycle-v1.4.mmd`](./diagrams/runtime-state-lifecycle-v1.4.mmd)

## State Domains

| Path | Purpose |
| --- | --- |
| `config/` | Agent, model, and policy configuration loaded at runtime |
| `sessions/` | Session ownership, message history, and workflow linkage |
| `workflows/` | Workflow state, lineage, steps, and status |
| `jobs/` | Queued, scheduled, running, failed, and completed job state |
| `workers/` | Worker leases, assignments, and transition history |
| `memories/` | Typed memory records and scoped summaries |
| `approvals/` | Approval requests and resume state |
| `artifacts/` | Runtime artifacts produced by workflows and tools |
| `logs/` | Trace and operational log output |

## Key Boundaries

- The FastAPI layer is intentionally thin. Route handlers mostly validate auth, unpack payloads, and delegate to runtime modules.
- The runtime is explicit rather than event-bus-heavy. Sessions, workflows, jobs, and workers are visible as first-class persisted records.
- The queue is local-state-backed, not an external broker. `jobs/` and `workers/` together capture scheduling, leasing, retry, and reclaim behavior.
- The model provider is an external dependency boundary. The runtime can target OpenAI-backed agents or a local Ollama server.
- Operator views are part of the same runtime. The control plane reads the same persisted state used by assistant execution rather than maintaining a separate monitoring store.

## Main Surfaces And Entry Points

- `/assistant`, `/widget`, `/widget.js`, and `/operator` are served in [`api/main.py`](../api/main.py).
- Session-backed assistant work starts in [`runtime/session.py`](../runtime/session.py).
- Workflow execution starts in [`runtime/workflow_runner.py`](../runtime/workflow_runner.py).
- Agent execution, policy evaluation, tool dispatch, and tracing live in [`runtime/agent.py`](../runtime/agent.py).
- Queue and worker execution live in [`runtime/queue.py`](../runtime/queue.py) and [`runtime/worker.py`](../runtime/worker.py).
- Operator inspection and recovery views live in [`runtime/control_plane.py`](../runtime/control_plane.py).

## Notes For Future Versions

`v1.5` work is expected to deepen the memory and continuity layer without changing the high-level container shape. If `v1.5` introduces a materially new subsystem or deployment boundary, add `docs/architecture-v1.5.md` rather than rewriting this released snapshot in place.
