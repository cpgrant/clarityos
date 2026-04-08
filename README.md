# ClarityOS

Minimal, explicit LLM runtime with workflows, queues, and typed memory.

## Status

- Current release: `v0.9`
- Current focus: `v1.0` trusted runtime
- Next target: `v1.0` slice 4 first production path and release criteria

Direction after `v1.0`: `v1.1` becomes the first assistant-surface milestone, with a web-first session gateway and operator UI on top of the existing runtime.

`v0.7` completes typed memory storage, bounded retrieval, explicit memory tools, workflow-linked memory summaries, and operator memory endpoints.

`v0.8` completes bounded delegation, child workflow lineage, explicit child role metadata, scoped shared-memory handoff, and operator-facing failure inspection.

`v0.9` completes state versioning and migrations, operator recovery and pruning controls, incident-correlation observability, operator auth, production policy hardening, and restart/partial-failure validation.

`v1.0` now starts the trusted-runtime layer with repeatable release validation drills, env-selectable production config profiles, and operator playbooks for maintenance and incident response.

## Historical Docs

Older milestone snapshots live in `docs/history/`:

- `docs/history/v0.1.md`
- `docs/history/v0.3.md`
- `docs/history/v0.6.md`
- `docs/history/v0.7.md`
- `docs/history/v0.8.md`
- `docs/history/v0.9.md`

## What It Does

Given an input, ClarityOS:

1. Loads agent config from YAML
2. Either builds a prompt or executes an allowed tool
3. Calls a model or returns a tool result
4. Returns a structured response
5. Writes a full execution trace

## Architecture

```text
API -> Agent -> Prompt/Tool -> Model/Tool Result -> Response
```

## Project Structure

```text
clarityos/
├── approvals/
├── artifacts/
├── api/
│   └── main.py
├── docs/
│   ├── playbooks/
│   │   ├── README.md
│   │   ├── incident-response.md
│   │   ├── migration.md
│   │   ├── queue-cleanup.md
│   │   ├── worker-repair.md
│   │   └── workflow-recovery.md
│   ├── production-profile.md
│   ├── roadmap.md
│   ├── v0.9-checklist.md
│   ├── v1.0-checklist.md
│   ├── v1.0-release-path.md
│   ├── v1.1-checklist.md
│   └── history/
│       ├── README.md
│       ├── v0.1.md
│       ├── v0.3.md
│       ├── v0.6.md
│       ├── v0.7.md
│       ├── v0.8.md
│       └── v0.9.md
├── memories/
├── jobs/
├── workers/
├── config/
│   ├── agents.yaml
│   ├── agents.production.yaml
│   ├── models.yaml
│   ├── policies.production.yaml
│   └── policies.yaml
├── logs/
├── runtime/
│   ├── agent.py
│   ├── approval.py
│   ├── artifact.py
│   ├── budget.py
│   ├── contracts.py
│   ├── control_plane.py
│   ├── errors.py
│   ├── memory.py
│   ├── model.py
│   ├── policy.py
│   ├── prompt_builder.py
│   ├── queue.py
│   ├── state.py
│   ├── trace.py
│   ├── tools.py
│   ├── worker.py
│   ├── workflow.py
│   └── workflow_runner.py
├── workflows/
├── scripts/
│   ├── run_release_validation.sh
│   └── show_latest_log.sh
├── tests/
│   ├── test_agent.py
│   ├── test_api.py
│   ├── test_control_plane.py
│   ├── test_memory.py
│   ├── test_model.py
│   ├── test_persistence_versions.py
│   ├── test_policy.py
│   ├── test_queue.py
│   ├── test_release_validation.py
│   ├── test_resilience.py
│   ├── test_worker.py
│   ├── test_workflow.py
│   └── test_workflow_runner.py
├── requirements.txt
└── README.md
```

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` tracks the direct runtime dependencies only.

## Environment

For OpenAI-backed agents:

```bash
export OPENAI_API_KEY=your_key_here
```

For Ollama-backed agents:

```bash
ollama serve
ollama pull llama3.1:latest
ollama pull gemma4:26b
```

The default Ollama base URL is `http://127.0.0.1:11434`. Set `OLLAMA_BASE_URL` only if your Ollama server is elsewhere.

For operator auth on control-plane endpoints:

```bash
export CLARITYOS_OPERATOR_TOKEN=replace_me_with_a_long_random_token
```

When `CLARITYOS_OPERATOR_TOKEN` is set, operator and control-plane endpoints require the `X-Operator-Token` header. If the variable is unset, operator auth stays disabled for local development.

For production policy hardening:

```bash
export CLARITYOS_ENV=production
```

In production mode, policies must explicitly deny `file_write` and `http`, and dangerous capability rules such as `exec`, `http`, and `file_write` must stay narrowly scoped. Agent-level policy overrides are disabled by default in production; opt in only if you mean it:

```bash
export CLARITYOS_ALLOW_AGENT_POLICY_OVERRIDES=1
```

To use the shipped production-oriented config examples without overwriting local development files:

```bash
export CLARITYOS_AGENTS_CONFIG=config/agents.production.yaml
export CLARITYOS_POLICIES_CONFIG=config/policies.production.yaml
```

If you want a separate model catalog for production, you can also point the runtime at a different models file:

```bash
export CLARITYOS_MODELS_CONFIG=config/models.yaml
```

## Run

```bash
source .venv/bin/activate
uvicorn api.main:app --reload
```

API base URL:

```text
http://127.0.0.1:8000
```

## Release Validation

For `v1.0` trusted-runtime checks, run the targeted recovery and resilience drills:

```bash
scripts/run_release_validation.sh
```

To run the targeted drills and then the full unit suite:

```bash
scripts/run_release_validation.sh --full
```

This validation path is intentionally narrower than a future soak/load harness. It is the first repeatable pre-release gate for:

- persisted recovery and replay drills
- expired-lease reclaim behavior
- retry-wait safe resume behavior
- batched queue and worker completion flows

## First Production Path

`v1.0` is not a chat product or multi-channel assistant release. The first supported production path is narrower:

- single-tenant
- self-hosted
- API-first
- queue-backed durable workflow execution
- operator-managed recovery and inspection

In other words, `v1.0` targets a trusted internal runtime for bounded assistant and research tasks started through workflow and job APIs. The full definition and release gates live in `docs/v1.0-release-path.md`.

## API

Health check:

```bash
curl http://127.0.0.1:8000/status
```

Operator auth status:

```bash
curl http://127.0.0.1:8000/operator/auth
```

Operator runtime profile:

```bash
curl http://127.0.0.1:8000/operator/profile \
  -H "X-Operator-Token: $CLARITYOS_OPERATOR_TOKEN"
```

Start a workflow with the default agent:

```bash
curl -X POST http://127.0.0.1:8000/workflows \
  -H "Content-Type: application/json" \
  -d '{"input":"Explain agents simply"}'
```

Compatibility alias using `/run`:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"input":"Explain agents simply"}'
```

Run the researcher agent:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"input":"Summarize climate risk in 3 bullets","agent":"researcher"}'
```

Run the local Ollama-backed agent:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"input":"Explain agents simply","agent":"local"}'
```

Run the local Gemma-backed agent:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"input":"Explain agents simply","agent":"local_gemma"}'
```

Run an allowed tool directly:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"default","tool":"echo","tool_args":{"text":"hello from tool"}}'
```

Read a repo file with a safe tool:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"default","tool":"read_file","tool_args":{"path":"README.md"}}'
```

Write a typed memory record explicitly:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"memory_operator","tool":"memory_write","tool_args":{"memory_type":"fact","scope_kind":"agent","agent":"researcher","payload":{"statement":"Retries are bounded","subject":"retry"},"tags":["runtime","retry"]}}'
```

Query memory explicitly with bounded retrieval:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"memory_operator","tool":"memory_query","tool_args":{"query":"retry","scope_kind":"agent","agent":"researcher","limit":3,"max_chars":400}}'
```

Inspect a workflow from the control plane when operator auth is enabled:

```bash
curl http://127.0.0.1:8000/workflows/wf-123 \
  -H "X-Operator-Token: $CLARITYOS_OPERATOR_TOKEN"
```

Inspect workflow incident rollups and causality chain:

```bash
curl "http://127.0.0.1:8000/incidents/workflows/wf-123?trace_limit=20" \
  -H "X-Operator-Token: $CLARITYOS_OPERATOR_TOKEN"
```

Inspect the compact incident summary:

```bash
curl "http://127.0.0.1:8000/incidents/workflows/wf-123/summary?trace_limit=20" \
  -H "X-Operator-Token: $CLARITYOS_OPERATOR_TOKEN"
```

Queue health with operator auth:

```bash
curl http://127.0.0.1:8000/queue/health \
  -H "X-Operator-Token: $CLARITYOS_OPERATOR_TOKEN"
```

## Deployment Notes

- Persisted runtime state lives under `workflows/`, `jobs/`, `workers/`, `memories/`, `artifacts/`, `approvals/`, and `logs/`; treat those directories as operational data.
- In production, set `CLARITYOS_OPERATOR_TOKEN` and terminate TLS in front of the API so operator headers are not exposed in plaintext.
- Set `CLARITYOS_ENV=production` in deployed environments so policy validation rejects broad unsafe capability rules and surprise agent-level overrides.
- Retention is still operator-managed in `v0.9`: use queue prune and state migration endpoints deliberately, and back up persisted state before destructive maintenance.
- Restart and partial-failure validation now covers persisted incident summaries, workflow recovery, and safe retry resume paths; deeper soak/load testing is still future work.
- The current trusted-runtime profile is documented in `docs/production-profile.md`.
- The first supported `v1.0` production use case and release gates are documented in `docs/v1.0-release-path.md`.
- Maintenance and incident procedures are documented in `docs/playbooks/README.md`.

Request an approval-gated tool run:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"supervised","tool":"echo","tool_args":{"text":"needs approval"}}'
```

The `/run` response returns:

- `status`
- `run_type`
- `agent`
- `policy`
- `budget_limits`
- `budget_used`
- `prompt`
- `provider`
- `model`
- `tool`
- `tool_args`
- `tool_output`
- `tool_result`
- `approval`
- `workflow`
- `artifacts`
- `retry` when a retryable failure is waiting on resume
- `output`

Invalid requests return structured JSON errors with HTTP `400`, `403`, `404`, `409`, or `429` instead of a generic internal server error.

Approval endpoints:

- `GET /approvals/{approval_id}`
- `POST /approvals/{approval_id}/approve`
- `POST /approvals/{approval_id}/deny`
- `POST /approvals/{approval_id}/abort`

Artifact endpoint:

- `GET /artifacts/{artifact_id}`

Memory endpoints:

- `GET /memories`
- `GET /memories/{memory_id}`
- `POST /memories/{memory_id}/delete`

`GET /memories` supports `memory_type`, `scope_kind`, `agent`, `workflow_id`, `run_id`, `tags`, and `limit` query parameters.

Job endpoints:

- `POST /jobs`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/cancel`
- `POST /jobs/{job_id}/reschedule`

Queue endpoints:

- `GET /queue`
- `POST /queue/promote-ready`

Worker endpoints:

- `POST /workers`
- `GET /workers`
- `GET /workers/{worker_id}`
- `POST /workers/{worker_id}/heartbeat`
- `POST /workers/{worker_id}/jobs/claim`
- `POST /workers/{worker_id}/jobs/{job_id}/run`
- `POST /workers/{worker_id}/jobs/run-next`
- `POST /workers/reclaim-expired`

Workflow endpoint:

- `POST /workflows`
- `GET /workflows/{workflow_id}` returns an operator-friendly control-plane view
- `POST /workflows/{workflow_id}/resume`
- `POST /workflows/{workflow_id}/subruns`

Queue a workflow job instead of running it immediately:

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"type":"workflow_start","agent":"default","input":"Explain agents simply","priority":100}'
```

Queue an idempotent workflow job so duplicate submits reuse the same record:

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"type":"workflow_start","agent":"default","input":"Explain agents simply","idempotency_key":"job-brief-001"}'
```

Queue a retryable workflow job with bounded backoff:

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"type":"workflow_start","agent":"default","input":"Explain agents simply","max_attempts":3,"retry_backoff_seconds":30}'
```

Queue a delayed resume job:

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"type":"workflow_resume","workflow_id":"<workflow_id>","delay_seconds":60}'
```

Cancel queued or claimed work safely:

```bash
curl -X POST http://127.0.0.1:8000/jobs/<job_id>/cancel \
  -H "Content-Type: application/json" \
  -d '{"reason":"operator canceled"}'
```

Reschedule queued or delayed work:

```bash
curl -X POST http://127.0.0.1:8000/jobs/<job_id>/reschedule \
  -H "Content-Type: application/json" \
  -d '{"delay_seconds":300}'
```

Register a worker and run the next queued job:

```bash
curl -X POST http://127.0.0.1:8000/workers \
  -H "Content-Type: application/json" \
  -d '{"name":"worker-1","lease_seconds":30}'
```

```bash
curl -X POST http://127.0.0.1:8000/workers/<worker_id>/jobs/run-next
```

Reclaim expired leases if a worker dies or misses its lease window:

```bash
curl -X POST http://127.0.0.1:8000/workers/reclaim-expired
```

Inspect queue depth and scheduled backlog:

```bash
curl http://127.0.0.1:8000/queue
```

The queue summary now includes status counts, total jobs, running job IDs, retry-pending scheduled job IDs, dead-letter job IDs, the oldest queued timestamp, and the next scheduled ready time.

Promote any due scheduled jobs immediately:

```bash
curl -X POST http://127.0.0.1:8000/queue/promote-ready
```

End-to-end approval flow:

1. Request the gated action and copy the returned `approval.approval_id`.
2. Approve it:

```bash
curl -X POST http://127.0.0.1:8000/approvals/<approval_id>/approve
```

3. Resume the same request with `approval_id`:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"supervised","tool":"echo","tool_args":{"text":"needs approval"},"approval_id":"<approval_id>"}'
```

You can also resume directly through the workflow:

```bash
curl -X POST http://127.0.0.1:8000/workflows/<workflow_id>/resume
```

Retryable failures are persisted as workflow state too. When a run hits a retryable error and still has retry budget left, the workflow moves to a `retry_wait:*` step and returns `status: "retry_wait"` with retry counters and the next retry timestamp.

Bounded child workflows can be started from an existing workflow too:

```bash
curl -X POST http://127.0.0.1:8000/workflows/<workflow_id>/subruns \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","role":"summarizer","input":"Summarize the parent result","allowed_capabilities":["model_call"],"shared_memory_ids":["<memory_id>"]}'
```

Child workflows inherit explicit lineage through `parent_workflow_id`, `root_workflow_id`, `depth`, and `child_workflow_ids`, and spawning is bounded by the parent workflow's configured subrun policy.

Each child workflow also persists an explicit delegation contract with assigned role metadata, allowed capabilities, allowed tools, and any shared-memory summaries handed off by the parent. Shared memory handoff is selective by `memory_id` and is surfaced in the child workflow snapshot, control-plane view, prompt context, and traces.

The workflow status endpoint now pulls the related control-plane state together in one response: current step details, approval summaries, artifact summaries, linked memory summaries, child workflow snapshots, handed-off shared memory, child failure summaries, containment status, and next valid actions like resume, approve, spawn subrun, or inspect linked memory.

## Logs

Each run creates:

```text
logs/run_<timestamp>.json
```

Each workflow also persists a durable record:

```text
workflows/<workflow_id>.json
```

Successful runs also persist durable output artifacts:

```text
artifacts/<artifact_id>.json
```

Queued work persists durable job records too:

```text
jobs/<job_id>.json
```

Job records now carry durable submission and operator state too, including `idempotency_key`, `cancel_reason`, `canceled_at`, worker claim metadata, reclaim metadata, and `ready_at` scheduling state.

Worker runtime state persists too:

```text
workers/<worker_id>.json
```

Failed jobs can now retry with bounded backoff using `max_attempts` and `retry_backoff_seconds`. Once retry budget is exhausted, the job moves to `dead_letter` and can be inspected with:

```bash
curl "http://127.0.0.1:8000/jobs?status=dead_letter"
```

Model-run success log example:

```json
{
  "version": "v0.8",
  "schema": "trace.v2",
  "timestamp": "...",
  "run_id": "...",
  "parent_run_id": null,
  "run_type": "model",
  "status": "success",
  "duration_ms": 12.3,
  "agent": "...",
  "policy_snapshot": {
    "name": "safe_readonly"
  },
  "budget": {
    "limits": {
      "max_steps": 4
    },
    "used": {
      "steps_used": 1
    }
  },
  "decision_log": [
    {
      "stage": "model_policy_check",
      "allowed": true
    }
  ],
  "workflow": {
    "workflow_id": "...",
    "status": "succeeded",
    "current_step_id": "finish_step"
  },
  "source_attribution": {
    "input": [
      {
        "type": "user_input"
      }
    ],
    "context": [
      {
        "type": "system_prompt"
      },
      {
        "type": "composed_prompt"
      }
    ],
    "output": {
      "type": "model"
    }
  },
  "cost_accounting": {
    "estimated_tokens": {
      "total": 42
    },
    "operations": {
      "model_calls": 1
    }
  },
  "context": {
    "input": "...",
    "prompt": "...",
    "model_alias": "fast"
  },
  "result": {
    "model": {
      "provider": "openai",
      "model": "gpt-4o-mini"
    },
    "output": "..."
  }
}
```

Tool-run success log example:

```json
{
  "version": "v0.8",
  "schema": "trace.v2",
  "timestamp": "...",
  "run_id": "...",
  "parent_run_id": null,
  "run_type": "tool",
  "status": "success",
  "duration_ms": 1.2,
  "agent": "default",
  "policy_snapshot": {
    "name": "safe_readonly"
  },
  "workflow": {
    "workflow_id": "...",
    "status": "succeeded",
    "current_step_id": "finish_step"
  },
  "source_attribution": {
    "input": [
      {
        "type": "user_input"
      },
      {
        "type": "tool_args"
      }
    ],
    "context": [],
    "output": {
      "type": "tool"
    }
  },
  "context": {
    "input": "",
    "prompt": null,
    "model_alias": null
  },
  "result": {
    "tool": {
      "name": "read_file",
      "ok": true,
      "input": {
        "args": {
          "path": "README.md"
        }
      },
      "output": {
        "value": "...file contents..."
      },
      "error": null
    },
    "output": "...file contents..."
  },
  "cost_accounting": {
    "operations": {
      "tool_calls": 1
    }
  }
}
```

Tool-run error logs include:

```json
{
  "version": "v0.8",
  "run_type": "tool",
  "status": "error",
  "decision_log": [
    {
      "stage": "tool_policy_check",
      "allowed": false
    }
  ],
  "result": {
    "tool": {
      "name": "read_file",
      "ok": false,
      "input": {
        "args": {
          "path": "../.bashrc"
        }
      },
      "error": {
        "failure_type": "tool_error",
        "error_type": "PolicyDeniedError",
        "message": "No allow rule matched ..."
      }
    },
    "error": {
      "error_type": "PolicyDeniedError",
      "message": "No allow rule matched ..."
    }
  },
  "budget": {
    "used": {
      "tool_calls_used": 1
    }
  }
}
```

Approval-pending logs include:

```json
{
  "version": "v0.8",
  "schema": "trace.v2",
  "run_type": "tool",
  "status": "pending",
  "decision_log": [
    {
      "stage": "tool_policy_check",
      "requires_approval": true
    },
    {
      "stage": "approval_requested",
      "approval_id": "..."
    }
  ],
  "workflow": {
    "workflow_id": "...",
    "status": "waiting",
    "current_step_id": "approval_wait:..."
  },
  "result": {
    "approval": {
      "approval_id": "...",
      "status": "pending"
    },
    "output": null
  },
  "cost_accounting": {
    "operations": {
      "approvals_requested": 1
    }
  }
}
```

Inspect the newest log:

```bash
scripts/show_latest_log.sh
```

## Testing

Run the minimal test suite:

```bash
python -m unittest discover -s tests -v
```

The tests cover:

- success path
- error path
- deterministic fake-model execution
- trace schema v2 creation
- explicit tool execution
- typed memory CRUD
- bounded memory retrieval
- memory policy denial and scoped memory access
- policy denial
- approval request and resume
- workflow state transitions
- workflow persistence and reload
- stepwise workflow execution from the saved pointer
- retry scheduling and retry resume guards
- bounded child workflow lineage
- durable workflow artifacts
- workflow-linked memory summaries
- workflow control-plane aggregation
- child failure inspection and containment reporting
- durable queue jobs with priority and delay
- worker registration, heartbeat, claiming, and job execution
- lease expiry detection and expired-job reclaim
- budget exhaustion
- API error mapping

## v0.8 Test Checklist

1. Run the automated tests:

```bash
python -m unittest discover -s tests -v
```

2. Start the API:

```bash
source .venv/bin/activate
uvicorn api.main:app --reload
```

3. Verify a model run:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"input":"Explain agents simply"}'
```

4. Verify the built-in tools:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"default","tool":"echo","tool_args":{"text":"hello from tool"}}'
```

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"default","tool":"get_time","tool_args":{}}'
```

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"default","tool":"read_file","tool_args":{"path":"README.md"}}'
```

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"memory_operator","tool":"memory_write","tool_args":{"memory_type":"fact","scope_kind":"agent","agent":"researcher","payload":{"statement":"Retries are bounded","subject":"retry"},"tags":["runtime","retry"]}}'
```

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"memory_operator","tool":"memory_query","tool_args":{"query":"retry","scope_kind":"agent","agent":"researcher","limit":3,"max_chars":400}}'
```

5. Verify safety behavior:

```bash
curl -i -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"default","tool":"read_file","tool_args":{"path":"../.bashrc"}}'
```

```bash
curl -i -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"default","tool":"read_file","tool_args":{"path":"missing.txt"}}'
```

```bash
curl -i -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"memory_operator","tool":"memory_write","tool_args":{"memory_type":"fact","scope_kind":"global","payload":{"statement":"global memory is restricted"}}}'
```

6. Verify workflow-linked memory and operator endpoints:

```bash
curl http://127.0.0.1:8000/workflows/<workflow_id>
```

```bash
curl "http://127.0.0.1:8000/memories?scope_kind=agent&agent=researcher&limit=5"
```

```bash
curl http://127.0.0.1:8000/memories/<memory_id>
```

7. Verify queued execution and worker processing:

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"type":"workflow_start","agent":"default","input":"Explain agents simply","max_attempts":3,"retry_backoff_seconds":30}'
```

```bash
curl -X POST http://127.0.0.1:8000/workers \
  -H "Content-Type: application/json" \
  -d '{"name":"worker-1","lease_seconds":30}'
```

```bash
curl http://127.0.0.1:8000/queue
```

```bash
curl -X POST http://127.0.0.1:8000/workers/<worker_id>/jobs/run-next
```

8. Inspect the latest trace:

```bash
scripts/show_latest_log.sh
```

## Design Principles

- explicit over implicit
- observable execution
- deterministic testing
- minimal architecture

## Roadmap

The detailed roadmap lives in `docs/roadmap.md`. Keep the README version short and update the detailed document first when milestone scope changes.

1. `v0.1` - execution
2. `v0.2` - traceability
3. `v0.2.1` - lightweight testing
4. `v0.2.2` - multi-provider support
5. `v0.3` - explicit tools
6. `v0.4` - control and safety
7. `v0.5` - workflows and control plane
8. `v0.6` - queues and jobs
9. `v0.7` - memory and retrieval
10. `v0.8` - multi-agent coordination
11. `v0.9` - production hardening
12. `v1.0` - release readiness and first production profile
13. `v1.1` - first assistant surface and session gateway

### `v0.7` Acceptance Criteria

- Typed memory records exist with explicit schemas such as `fact`, `summary`, `observation`, and `artifact_ref`.
- Durable memory storage supports create, read, list, and bounded query operations.
- `memory_read` and `memory_write` are enforced through the existing policy layer.
- Retrieval is bounded by explicit limits and returns source metadata instead of silently dumping full memory state into prompts.
- Memory activity appears in traces and the workflow control plane.
- Automated tests cover memory CRUD, bounded retrieval, policy denial, and workflow integration.

### `v0.8` Acceptance Criteria

- Workflows can coordinate bounded child agents with explicit lineage and role assignment.
- Agent delegation respects configurable limits for depth, fan-out, and allowed capabilities.
- Agents can read shared memory selectively and write scoped memory intentionally.
- Multi-agent execution is inspectable through traces, workflow state, and control-plane views.
- Failures in one child workflow do not silently corrupt sibling or parent workflow state.
- Automated tests cover delegation, lineage, scoped memory access, and failure isolation.

`v0.9` is complete. The next planned milestone lives in `docs/roadmap.md` and is `v1.0` trusted runtime, with validation, rollout defaults, operator playbooks, and a narrow first production path.

### `v0.9` Acceptance Criteria

- Durable state formats are versioned and have a clear migration path.
- Operators can inspect, replay, prune, and recover workflows, jobs, artifacts, and memory safely.
- Auth, access control, retention, and audit expectations are defined for production deployment.
- Queue, worker, memory, and workflow subsystems expose enough observability for incident debugging.
- System behavior under retry, reclaim, restart, and partial-failure conditions is documented and tested.
- Production hardening includes load, soak, and recovery validation beyond the minimal unit suite.

### `v1.0` Acceptance Criteria

- The runtime has an explicit production profile with rollout defaults, deployment guidance, and hardened operator posture.
- Recovery, retry, reclaim, and restart behavior are validated through repeatable load and failure drills beyond unit coverage.
- Operators have compact incident summaries, safe maintenance flows, and a documented operational playbook.
- Release criteria for the first real production use case are defined, measurable, and documented.

`v1.0` first production path:

- API-first, self-hosted, single-tenant workflow runtime
- bounded default/researcher-style agent execution
- queue/worker-backed async execution with operator recovery
- no assistant UI, multi-channel surface, or plugin ecosystem yet

### `v1.1` Acceptance Criteria

- ClarityOS supports explicit user conversation/session records that map into workflows, memory, and operator-visible history.
- A first assistant surface exists, ideally web-first, that uses the existing runtime instead of introducing a second execution path.
- Operators can inspect live conversations, related workflows, and recovery actions through a simple UI.
- Any first channel adapter remains thin and transport-focused, with workflow, queue, memory, and recovery behavior still owned by the runtime core.
