# ClarityOS

Minimal, explicit LLM execution runtime.

## Status

- Current release: `v0.5`
- Current focus: `v0.6` queue + workers
- Next target: `v0.7` typed memory + bounded retrieval

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
├── config/
│   ├── agents.yaml
│   ├── models.yaml
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
│   ├── model.py
│   ├── policy.py
│   ├── prompt_builder.py
│   ├── trace.py
│   ├── tools.py
│   ├── workflow.py
│   └── workflow_runner.py
├── workflows/
├── scripts/
│   └── show_latest_log.sh
├── tests/
│   ├── test_agent.py
│   ├── test_api.py
│   ├── test_control_plane.py
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

## Environment

For OpenAI-backed agents:

```bash
export OPENAI_API_KEY=your_key_here
```

For Ollama-backed agents:

```bash
ollama serve
ollama pull llama3.1:latest
```

The default Ollama base URL is `http://127.0.0.1:11434`. Set `OLLAMA_BASE_URL` only if your Ollama server is elsewhere.

## Run

```bash
source .venv/bin/activate
uvicorn api.main:app --reload
```

API base URL:

```text
http://127.0.0.1:8000
```

## API

Health check:

```bash
curl http://127.0.0.1:8000/status
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

Workflow endpoint:

- `POST /workflows`
- `GET /workflows/{workflow_id}` returns an operator-friendly control-plane view
- `POST /workflows/{workflow_id}/resume`
- `POST /workflows/{workflow_id}/subruns`

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
  -d '{"agent":"researcher","input":"Summarize the parent result"}'
```

Child workflows inherit explicit lineage through `parent_workflow_id`, `root_workflow_id`, `depth`, and `child_workflow_ids`, and spawning is bounded by the parent workflow's configured subrun policy.

The workflow status endpoint now pulls the related control-plane state together in one response: current step details, approval summaries, artifact summaries, child workflow snapshots, and next valid actions like resume, approve, or spawn subrun.

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

Model-run success log example:

```json
{
  "version": "v0.5",
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
  "version": "v0.5",
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
  "version": "v0.5",
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
  "version": "v0.5",
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
- policy denial
- approval request and resume
- workflow state transitions
- workflow persistence and reload
- stepwise workflow execution from the saved pointer
- retry scheduling and retry resume guards
- bounded child workflow lineage
- durable workflow artifacts
- workflow control-plane aggregation
- budget exhaustion
- API error mapping

## v0.5 Test Checklist

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

6. Inspect the latest trace:

```bash
scripts/show_latest_log.sh
```

## Design Principles

- explicit over implicit
- observable execution
- deterministic testing
- minimal architecture

## Roadmap

- `v0.1` - execution
- `v0.2` - traceability
- `v0.2.1` - lightweight testing
- `v0.2.2` - multi-provider support
- `v0.3` - explicit tools
- `v0.4` - control and safety
- `v0.5` - workflows and control plane
- `v0.6` - queues and jobs
- `v0.7` - memory and retrieval
- `v0.8` - multi-agent coordination
- `v0.9` - production hardening
