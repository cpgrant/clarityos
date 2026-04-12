# ClarityClaw Runtime Architecture v1.7

This document describes the released runtime architecture for `v1.7`.

Scope:

- assistant browser surface
- embeddable widget surface
- operator control plane
- packaged API and worker startup profile
- runtime orchestration and bounded child-workflow execution
- session continuity and bounded carry-forward
- storage-root, backup, and packaged deployment posture
- operator runtime-posture and maintenance views
- persisted state on local disk
- external model providers

## Summary

ClarityClaw `v1.7` keeps the thin FastAPI-over-runtime shape from `v1.6`, but it now makes the first packaged self-hosted deployment boundary explicit rather than depending on repo habits and local operator knowledge.

Compared with the released `v1.6` snapshot, the `v1.7` shape adds a clearer packaged deployment layer through:

- `Containerfile` and `compose.yaml` for the first supported self-hosted startup path
- `runtime.worker_loop` as the first repeatable packaged background runner
- `runtime.storage` and `CLARITYOS_STATE_ROOT` for an explicit persisted-state root contract
- stronger operator runtime posture in `runtime.control_plane`

The runtime centers on:

- session-backed assistant interactions and continuity state in [`runtime/session.py`](../runtime/session.py)
- workflow, child-workflow, and delegation execution in [`runtime/workflow_runner.py`](../runtime/workflow_runner.py)
- workflow state persistence and lineage metadata in [`runtime/workflow.py`](../runtime/workflow.py)
- agent execution, policy checks, prompt building, and tracing in [`runtime/agent.py`](../runtime/agent.py)
- queue and worker coordination in [`runtime/queue.py`](../runtime/queue.py), [`runtime/worker.py`](../runtime/worker.py), and [`runtime/worker_loop.py`](../runtime/worker_loop.py)
- operator, runtime-posture, continuity, workflow-control, and incident views in [`runtime/control_plane.py`](../runtime/control_plane.py)
- packaged storage-root posture in [`runtime/storage.py`](../runtime/storage.py)

Persisted JSON state under `sessions/`, `workflows/`, `jobs/`, `workers/`, `memories/`, `approvals/`, `artifacts/`, and `logs/` remains the system of record for runtime state. In `v1.7`, the supported packaged profile makes the state root explicit rather than treating the repo root as an implicit deployment boundary.

Mermaid sources for the diagrams in this document live in `docs/diagrams/`.

## Container View

Source:

- [`docs/diagrams/architecture-v1.7.mmd`](./diagrams/architecture-v1.7.mmd)

## System Context View

This view shows ClarityClaw as a packaged self-hosted system in relation to assistant users, host sites, operators, and model providers.

Source:

- [`docs/diagrams/system-context-v1.7.mmd`](./diagrams/system-context-v1.7.mmd)

## Assistant Message Flow

This is the main synchronous browser-first path for `/assistant` and the iframe-backed widget, including continuity loading and packaged persisted-state handling.

Source:

- [`docs/diagrams/assistant-message-flow-v1.7.mmd`](./diagrams/assistant-message-flow-v1.7.mmd)

## Background Job Flow

This is the asynchronous path for queued starts, resumes, packaged worker-loop polling, and bounded child subruns.

Source:

- [`docs/diagrams/background-job-flow-v1.7.mmd`](./diagrams/background-job-flow-v1.7.mmd)

## Runtime State Lifecycle View

This view summarizes the released `v1.7` state transitions for sessions, workflows, jobs, workers, packaged deployment posture, and operator runtime support state.

Source:

- [`docs/diagrams/runtime-state-lifecycle-v1.7.mmd`](./diagrams/runtime-state-lifecycle-v1.7.mmd)

## State Domains

| Path | Purpose |
| --- | --- |
| `config/` | Agent, model, and policy configuration loaded at runtime |
| `sessions/` | Session ownership, message history, continuity summaries, and workflow linkage |
| `workflows/` | Workflow state, lineage, delegation contracts, child synthesis, and audit metadata |
| `jobs/` | Queued, scheduled, running, failed, and completed job state |
| `workers/` | Worker leases, assignments, transition history, and packaged worker-loop coordination |
| `memories/` | Typed memory records, workflow-linked summaries, and continuity support state |
| `approvals/` | Approval requests and resume state |
| `artifacts/` | Runtime artifacts produced by workflows and tools |
| `logs/` | Trace, incident-correlation, and operator-facing operational log output |

## Key Boundaries

- The FastAPI layer is intentionally thin. Route handlers mostly validate auth, unpack payloads, and delegate to runtime modules.
- The packaged deployment profile is now explicit. `Containerfile`, `compose.yaml`, and `runtime.worker_loop` define the first supportable startup path for self-hosted use.
- Persisted state is still local-state-backed, not an external platform dependency. `CLARITYOS_STATE_ROOT` makes the supported storage root explicit for packaged deployments.
- The queue is still local-state-backed, not an external broker. `jobs/` and `workers/` together still capture scheduling, leasing, retry, reclaim, and background execution behavior.
- Operator views are part of the same runtime. The control plane reads the same persisted state used by assistant execution rather than maintaining a separate monitoring store.
- The new operator runtime-posture layer is still bounded. It summarizes session, queue, worker, and storage posture without creating a separate automation or orchestration subsystem.
- The model provider remains an external dependency boundary. The runtime can target OpenAI-backed agents or a local Ollama server.

## Main Surfaces And Entry Points

- `/assistant`, `/widget`, `/widget.js`, and `/operator` are served in [`api/main.py`](../api/main.py).
- Session-backed assistant work and continuity handling start in [`runtime/session.py`](../runtime/session.py).
- Workflow execution and bounded child delegation start in [`runtime/workflow_runner.py`](../runtime/workflow_runner.py).
- Workflow state and lineage persistence live in [`runtime/workflow.py`](../runtime/workflow.py).
- Agent execution, policy evaluation, tool dispatch, and tracing live in [`runtime/agent.py`](../runtime/agent.py).
- Queue, worker execution, and packaged worker-loop execution live in [`runtime/queue.py`](../runtime/queue.py), [`runtime/worker.py`](../runtime/worker.py), and [`runtime/worker_loop.py`](../runtime/worker_loop.py).
- Operator inspection, runtime-posture views, continuity views, and incident recovery views live in [`runtime/control_plane.py`](../runtime/control_plane.py).
- Packaged storage-root and backup posture live in [`runtime/storage.py`](../runtime/storage.py).

## Notes For Future Versions

`v1.8` work is expected to add careful external integration while preserving the released `v1.7` packaged self-hosted runtime boundaries. If `v1.8` introduces a materially new external-integration layer, add `docs/architecture-v1.8.md` rather than rewriting this released snapshot in place.
