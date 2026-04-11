# ClarityOS

Minimal, explicit LLM runtime with workflows, queues, and typed memory.

## Status

- Current release: `v1.6`
- Current focus: `v1.7` deployment and operator maturity
- Next target: `v1.7` release validation and release promotion

Direction after `v1.6`: `v1.7` should make ClarityOS easier to package, deploy, and operate repeatedly as a self-hosted assistant system.

The active `v1.7` execution plan now lives in `docs/v1.7-checklist.md`.

`v1.6` is now the current release. It completes the bounded multi-agent quality layer: explicit delegation contracts, supervisor-style child-result synthesis, delegated-run auditability, and a narrow release path for supportable parent-child workflow coordination.

`v1.7` Slice 1 is complete through a first `Containerfile`, `compose.yaml`, `.dockerignore`, a packaged worker-loop entrypoint, and a documented packaged runtime profile for API and background execution.
`v1.7` Slice 2 is complete through an explicit `CLARITYOS_STATE_ROOT` contract, operator-visible storage and backup posture, a single packaged state mount, and a storage/backup playbook for repeatable self-hosted deployments.
`v1.7` Slice 3 is complete through a runtime-posture dashboard summary, clearer packaged-runtime guidance in the operator console, and an operator runtime playbook for repeated self-hosted operation.
`v1.7` Slice 4 is complete through an explicit release path for the first supportable packaged self-hosted deployment profile, including release gates and narrow support boundaries.

`v1.6` Slice 1 is complete through explicit delegation contract fields, bounded child-task briefs, and earlier validation for invalid delegated work.
`v1.6` Slice 2 is complete through supervisor-style child-result synthesis, bounded next-action guidance, and clearer child rollups in workflow inspection.
`v1.6` Slice 3 is complete through delegated-run audit summaries, contract-gap and output-gap surfacing, and delegation-denied trace visibility in incident review.
`v1.6` Slice 4 is complete through an explicit release path for the first bounded multi-agent workflow profile, including supported shape, out-of-scope boundaries, and release gates.

`v1.4` is complete through a cleaner explicit tool registry, stronger bounded retrieval outputs, and narrow runtime-maintenance action tools that stay policy-scoped and operator-safe.

`v1.5` completes the memory and continuity layer: summarization, compaction, carry-forward rules, stronger operator visibility, and a narrow release path for long-running browser-first assistant sessions.

`v1.5` Slice 1 is complete through explicit session continuity compaction helpers, persisted compaction metadata with source references, and operator-visible continuity state.

`v1.5` Slice 2 is complete through persisted session-level continuity summaries, bounded carry-forward for assistant turns, and visibility for continuity summaries in session and control-plane state.

`v1.5` Slice 3 is complete through explicit continuity budget rules, operator-facing compact/recompact recommendations, and continuity cleanup guidance in the session playbook.

`v1.5` Slice 4 is complete through an explicit release path for the first memory-maturity use case, including supported shape, out-of-scope boundaries, and release gates.

Recent release notes live in `docs/v1.6-checklist.md`, `docs/v1.6-release-path.md`, `docs/architecture-v1.6.md`, and `docs/history/v1.6.md`.

`v1.7` is now the active milestone. It should focus on deployment repeatability, operator ergonomics, and clearer packaged runtime expectations rather than expanding autonomy.
Companion planning notes for `v1.7` live in `docs/differentiators.md` and `docs/v1.7-release-path.md`.

After `v1.6`, the action side still remains intentionally narrow. Repo write helpers, hidden preference learning, and proactive autonomy are still explicitly deferred beyond this release line.

`v0.7` completes typed memory storage, bounded retrieval, explicit memory tools, workflow-linked memory summaries, and operator memory endpoints.

`v0.8` completes bounded delegation, child workflow lineage, explicit child role metadata, scoped shared-memory handoff, and operator-facing failure inspection.

`v0.9` completes state versioning and migrations, operator recovery and pruning controls, incident-correlation observability, operator auth, production policy hardening, and restart/partial-failure validation.

`v1.0` completes the trusted-runtime layer with repeatable release validation drills, env-selectable production config profiles, operator playbooks, and an explicit first production path with measurable release gates.

`v1.1` completes explicit persisted sessions, conversation-to-workflow mapping, session control-plane inspection, a minimal web-first assistant surface, an operator console, and a first embeddable web widget gateway on top of the trusted runtime.

`v1.2` completes assistant deployment hardening: session ownership and surface auth, widget deployment policy and branding posture, operator playbooks and session maintenance flows, and an explicit first deployed assistant path with release gates.

## Historical Docs

Older milestone snapshots live in `docs/history/`:

- `docs/history/v0.1.md`
- `docs/history/v0.3.md`
- `docs/history/v0.6.md`
- `docs/history/v0.7.md`
- `docs/history/v0.8.md`
- `docs/history/v0.9.md`
- `docs/history/v1.0.md`
- `docs/history/v1.1.md`
- `docs/history/v1.2.md`
- `docs/history/v1.3.md`
- `docs/history/v1.4.md`
- `docs/history/v1.5.md`
- `docs/history/v1.6.md`

## What It Does

Given an input, ClarityOS:

1. Loads agent config from YAML
2. Either builds a prompt or executes an allowed tool
3. Calls a model or returns a tool result
4. Returns a structured response
5. Writes a full execution trace

## Top Example Use Cases

- Repo-aware assistant for one codebase: answer questions about code, docs, architecture, and runtime behavior using explicit bounded retrieval instead of vague chat responses
- Long-running research or planning threads: keep a topic coherent across many turns with persisted session continuity, summaries, and bounded carry-forward
- Runtime troubleshooting assistant: inspect workflows, jobs, workers, incidents, and recovery state to help explain what failed and what should happen next
- Operator support console: give operators a browser surface for session inspection, workflow recovery, continuity review, and maintenance decisions
- Structured multi-step task execution: run bounded workflow-backed tasks with explicit state, traces, and inspectable intermediate results
- Embeddable self-hosted assistant: power a narrow browser-first assistant through `/assistant`, `/widget`, and `/widget.js`

ClarityOS is intentionally better suited to supportable, inspectable assistant work than to open-ended autonomous behavior, hidden learning, or many-channel consumer assistant sprawl.

## Architecture

```text
API -> Agent -> Prompt/Tool -> Model/Tool Result -> Response
```

Released architecture snapshots live in `docs/architecture-v1.6.md` and `docs/architecture-v1.4.md`.

## Project Structure

```text
clarityos/
├── .dockerignore
├── Containerfile
├── approvals/
├── artifacts/
├── api/
│   └── main.py
├── compose.yaml
├── docs/
│   ├── architecture-v1.4.md
│   ├── architecture-v1.6.md
│   ├── architecture.md
│   ├── diagrams/
│   ├── playbooks/
│   │   ├── README.md
│   │   ├── incident-response.md
│   │   ├── migration.md
│   │   ├── queue-cleanup.md
│   │   ├── storage-backup.md
│   │   ├── worker-repair.md
│   │   └── workflow-recovery.md
│   ├── production-profile.md
│   ├── differentiators.md
│   ├── roadmap.md
│   ├── v0.9-checklist.md
│   ├── v1.0-checklist.md
│   ├── v1.0-release-path.md
│   ├── v1.1-checklist.md
│   ├── v1.2-checklist.md
│   ├── v1.2-release-path.md
│   ├── v1.3-checklist.md
│   ├── v1.3-release-path.md
│   ├── v1.4-checklist.md
│   ├── v1.4-release-path.md
│   ├── v1.5-checklist.md
│   ├── v1.5-memory-strategy.md
│   ├── v1.5-release-path.md
│   ├── v1.6-checklist.md
│   ├── v1.6-release-path.md
│   ├── v1.7-checklist.md
│   ├── v1.7-release-path.md
│   └── history/
│       ├── README.md
│       ├── v0.1.md
│       ├── v0.3.md
│       ├── v0.6.md
│       ├── v0.7.md
│       ├── v0.8.md
│       ├── v0.9.md
│       ├── v1.0.md
│       ├── v1.1.md
│       ├── v1.2.md
│       ├── v1.3.md
│       ├── v1.4.md
│       ├── v1.5.md
│       └── v1.6.md
├── memories/
├── sessions/
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
│   ├── session.py
│   ├── state.py
│   ├── tool_support.py
│   ├── trace.py
│   ├── storage.py
│   ├── tools.py
│   ├── tools_actions.py
│   ├── tools_memory.py
│   ├── tools_repo.py
│   ├── tools_runtime.py
│   ├── tools_utility.py
│   ├── tools_web.py
│   ├── worker.py
│   ├── worker_loop.py
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
│   ├── test_session.py
│   ├── test_worker.py
│   ├── test_worker_loop.py
│   ├── test_workflow.py
│   └── test_workflow_runner.py
├── ui/
│   ├── assistant.html
│   ├── operator.html
│   ├── widget.html
│   └── widget.js
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

For the embeddable widget, you can narrow which sites are allowed to host it and set branding defaults without editing code:

```bash
export CLARITYOS_WIDGET_ENABLED=1
export CLARITYOS_WIDGET_ALLOWED_ORIGINS=https://app.example.com,https://admin.example.com
export CLARITYOS_WIDGET_ALLOWED_AGENTS=researcher,default
export CLARITYOS_WIDGET_BRAND_NAME="Site Assistant"
export CLARITYOS_WIDGET_BRAND_TAGLINE="Ask the session-backed assistant"
export CLARITYOS_WIDGET_BRAND_ACCENT="#176b52"
export CLARITYOS_WIDGET_DEFAULT_AGENT=researcher
export CLARITYOS_WIDGET_LAUNCHER_LABEL=Ask
export CLARITYOS_WIDGET_LAUNCHER_POSITION=right
export CLARITYOS_WIDGET_LAUNCHER_DEFAULT_OPEN=0
```

If `CLARITYOS_WIDGET_ALLOWED_ORIGINS` is unset, the widget defaults to same-origin embedding only. The widget now also publishes deployment-oriented iframe headers, limits embed agents through `CLARITYOS_WIDGET_ALLOWED_AGENTS`, and can be disabled entirely with `CLARITYOS_WIDGET_ENABLED=0`.

Assistant-facing sessions now use an explicit per-session token for browser and embed access. New sessions created through `/sessions` return a `session_token`; assistant surfaces send it back through `X-Session-Token` on `/assistant/sessions/{session_id}` and `/sessions/{session_id}/messages`. Operator routes remain separately protected by `X-Operator-Token`.

Assistant-surface operators now have dedicated playbooks in [docs/playbooks/README.md](/home/cpgrant/development/codex/clarityos/docs/playbooks/README.md) for:
- assistant-surface incidents
- widget deployment mistakes
- session archive and prune flows

## Run

```bash
source .venv/bin/activate
uvicorn api.main:app --reload
```

API base URL:

```text
http://127.0.0.1:8000
```

Minimal assistant surface:

```text
http://127.0.0.1:8000/assistant
```

Operator console:

```text
http://127.0.0.1:8000/operator
```

Embeddable widget frame:

```text
http://127.0.0.1:8000/widget
```

## Packaged Run (`v1.7` Slice 1 Baseline)

The first packaged self-hosted profile now ships with:

- `Containerfile` for the API/runtime image
- `compose.yaml` for a two-service packaged baseline
- `python -m runtime.worker_loop` for repeatable background job execution

The packaged profile assumes `.env` contains the environment values you want the services to inherit.

Start the packaged profile with Podman Compose:

```bash
podman compose up --build
```

Or with Docker Compose:

```bash
docker compose up --build
```

The packaged baseline runs:

- `api`: `uvicorn api.main:app --host 0.0.0.0 --port 8000`
- `worker`: `python -m runtime.worker_loop --name packaged-worker --poll-seconds 2`

The packaged baseline also sets:

```bash
CLARITYOS_STATE_ROOT=/app/state
```

The compose profile bind-mounts that one state root so the persisted runtime tree survives container restarts:

- `/app/state/sessions`
- `/app/state/workflows`
- `/app/state/jobs`
- `/app/state/workers`
- `/app/state/memories`
- `/app/state/artifacts`
- `/app/state/approvals`
- `/app/state/logs`

You can inspect the active storage posture through `GET /operator/profile`, which now reports the configured state root, per-directory backup priority, and which directories must be preserved versus can be regenerated.

Current `v1.1` assistant surface scope:

- web-first and single-browser-session oriented
- creates or reloads a persisted session automatically
- sends messages through `POST /sessions/{session_id}/messages`
- refreshes/polls state through `GET /assistant/sessions/{session_id}`
- keeps operator-only control and recovery views behind the existing operator-authenticated endpoints
- does not yet include a multi-user auth layer or any external channels

Current operator console scope:

- reads sessions, queue health, worker health, and selected session control data from the existing operator endpoints
- prompts for the operator token only when `CLARITYOS_OPERATOR_TOKEN` is configured
- surfaces current workflow recovery actions through the browser for safe resume, replay, and recover flows
- remains a thin control-plane client rather than a second execution or policy layer

Current gateway adapter scope:

- uses an embeddable web widget rather than Telegram, Slack, or any hosted third-party transport
- launches a floating iframe through `/widget.js` and runs the widget UI in `/widget`
- still creates and uses persisted sessions through the existing `/sessions` flow
- supports explicit allowed-origin controls, allowed-agent policy, launcher posture, and branding defaults through env-configured widget settings
- remains browser-only and same-runtime, so deployment stays narrow and self-hosted

## First Assistant Deployment Path

`v1.2` defines the first narrow deployed assistant profile:

- self-hosted
- single-tenant
- browser-first
- `/assistant` as the primary surface
- `/widget` and `/widget.js` as an optional embedded surface
- explicit session ownership and operator-authenticated maintenance

What is intentionally supported:

- internal assistant and research threads through persisted sessions
- explicit browser/session auth posture
- narrow widget deployment with allowed origins, allowed agents, and branding defaults
- operator maintenance through session control, archive, prune, and workflow recovery

What is still intentionally unsupported:

- Telegram, Slack, Discord, SMS, or other non-browser transports
- hosted hub or multi-tenant assistant operation
- consumer-style identity and account systems
- broad autonomous channel sprawl

The full deployment-path definition and release gates live in `docs/v1.2-release-path.md`.

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

Create a session:

```bash
curl -X POST http://127.0.0.1:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"title":"Research thread","agent":"researcher"}'
```

Append a user message to a session:

```bash
curl -X POST http://127.0.0.1:8000/sessions/session-123/messages \
  -H "Content-Type: application/json" \
  -d '{"input":"Summarize the latest workflow state","agent":"researcher"}'
```

Open the web-first assistant surface:

```text
http://127.0.0.1:8000/assistant
```

Read back a session for the assistant browser flow:

```bash
curl http://127.0.0.1:8000/assistant/sessions/session-123 \
  -H "X-Session-Token: $CLARITYOS_SESSION_TOKEN"
```

Create a session and capture the returned token:

```bash
curl -X POST http://127.0.0.1:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"title":"Web Assistant","agent":"researcher","surface":"assistant_web"}'
```

Open the operator console in the browser:

```text
http://127.0.0.1:8000/operator
```

The console uses the existing protected endpoints underneath. If operator auth is enabled, paste the same `CLARITYOS_OPERATOR_TOKEN` value into the browser console prompt field.

Load the compact operator dashboard payload directly:

```bash
curl http://127.0.0.1:8000/operator/dashboard \
  -H "X-Operator-Token: $CLARITYOS_OPERATOR_TOKEN"
```

Behind the UI, the operator console reads and acts through:

```bash
curl http://127.0.0.1:8000/sessions \
  -H "X-Operator-Token: $CLARITYOS_OPERATOR_TOKEN"
```

```bash
curl http://127.0.0.1:8000/queue/health \
  -H "X-Operator-Token: $CLARITYOS_OPERATOR_TOKEN"
```

```bash
curl http://127.0.0.1:8000/workers/health \
  -H "X-Operator-Token: $CLARITYOS_OPERATOR_TOKEN"
```

Embed the widget on another page:

```html
<script
  src="http://127.0.0.1:8000/widget.js"
  data-title="Site Assistant"
  data-agent="researcher"
  data-label="Ask"
></script>
```

Direct widget frame URL:

```text
http://127.0.0.1:8000/widget?title=Site%20Assistant&agent=researcher
```

Inspect widget runtime config and allowed-origin posture:

```bash
curl "http://127.0.0.1:8000/widget/config?origin=https://app.example.com"
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

Inspect a session and its related workflow rollups:

```bash
curl http://127.0.0.1:8000/sessions/session-123/control \
  -H "X-Operator-Token: $CLARITYOS_OPERATOR_TOKEN"
```

Archive an assistant-facing session:

```bash
curl -X POST http://127.0.0.1:8000/sessions/session-123/archive \
  -H "Content-Type: application/json" \
  -H "X-Operator-Token: $CLARITYOS_OPERATOR_TOKEN" \
  -d '{"reason":"support cleanup"}'
```

Prune old archived sessions:

```bash
curl -X POST http://127.0.0.1:8000/sessions/prune \
  -H "Content-Type: application/json" \
  -H "X-Operator-Token: $CLARITYOS_OPERATOR_TOKEN" \
  -d '{"statuses":["archived"],"older_than_hours":168,"limit":25}'
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

List repo files with a safe tool:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"list_files","tool_args":{"path":".","pattern":"*.md","limit":10}}'
```

List one repo directory with a bounded navigation tool:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"list_directory","tool_args":{"path":"runtime","limit":20}}'
```

Search repo files with a safe tool:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"search_files","tool_args":{"path":".","query":"ClarityOS","pattern":"*.md","limit":10}}'
```

Read a specific file range with a safe tool:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"read_file_range","tool_args":{"path":"README.md","start_line":1,"end_line":12}}'
```

Fetch a controlled external text or HTML page:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"fetch_url","tool_args":{"url":"https://docs.openclaw.ai/","max_chars":1200}}'
```

Inspect a session with a compact runtime tool:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"inspect_session","tool_args":{"session_id":"<session_id>"}}'
```

Inspect a workflow with a compact runtime tool:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"inspect_workflow","tool_args":{"workflow_id":"<workflow_id>"}}'
```

Inspect queue health and a compact job list:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"inspect_queue","tool_args":{"limit":5}}'
```

Inspect a worker with compact health context:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"inspect_worker","tool_args":{"worker_id":"<worker_id>"}}'
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

Common retrieval output shapes:

- `list_directory`
  Returns `path`, `entry_count`, `directory_count`, `file_count`, `truncated`, and bounded `entries`.
- `list_files`
  Returns `path`, `result_count`, `scanned_file_count`, `truncated`, bounded `files`, and compact `file_previews`.
- `search_files`
  Returns `query`, `result_count`, `matched_file_count`, `matched_files`, `files_scanned`, and `hits` with `match_preview`, `context_before`, and `context_after`.
- `read_file_range`
  Returns `path`, `start_line`, `end_line`, `line_count`, `total_line_count`, `content_preview`, and full bounded `content`.
- `fetch_url`
  Returns `url`, `domain`, `status_code`, `content_type`, `content_length`, `summary`, `content_preview`, `content`, and `truncated`.
- `inspect_session`, `inspect_workflow`, `inspect_queue`, `inspect_worker`
  Return a top-level `summary` plus the detailed structured payload for the inspected runtime entity.
- `archive_session`, `prune_sessions`, `promote_ready_jobs`, `repair_stale_jobs`, `repair_orphaned_workers`, `safe_resume_workflow`, `replay_workflow`, `recover_workflow`
  Are narrow maintenance actions intended for `maintenance_operator`, not for general-purpose assistant use.
- Repo write helpers are intentionally not part of the `v1.4` shipped action set.

When to use `maintenance_operator`:

- use it for explicit runtime maintenance such as archiving sessions, promoting due jobs, repairing stale queue/worker state, and resuming or recovering workflows
- do not use it for general assistant Q&A, repo research, or broad mutation tasks
- treat it like an operator-facing helper with a narrow, supportable action set

When you want a human-readable tool result during manual testing, filter the `/run` envelope with `jq`:

```bash
curl -s -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"search_files","tool_args":{"path":"runtime","query":"session","pattern":"*.py","limit":5}}' \
  | jq '{status, tool, tool_output}'
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
- Retention is still operator-managed in `v1.0`: use queue prune and state migration endpoints deliberately, and back up persisted state before destructive maintenance.
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
  -d '{"agent":"researcher","tool":"list_files","tool_args":{"path":".","pattern":"*.md","limit":10}}'
```

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"list_directory","tool_args":{"path":"runtime","limit":20}}'
```

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"search_files","tool_args":{"path":".","query":"ClarityOS","pattern":"*.md","limit":10}}'
```

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"read_file_range","tool_args":{"path":"README.md","start_line":1,"end_line":12}}'
```

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"inspect_session","tool_args":{"session_id":"<session_id>"}}'
```

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"inspect_workflow","tool_args":{"workflow_id":"<workflow_id>"}}'
```

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"inspect_queue","tool_args":{"limit":5}}'
```

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"inspect_worker","tool_args":{"worker_id":"<worker_id>"}}'
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

Run a narrow maintenance action explicitly:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"maintenance_operator","tool":"archive_session","tool_args":{"session_id":"<session_id>","reason":"support cleanup"}}'
```

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"maintenance_operator","tool":"repair_orphaned_workers","tool_args":{"limit":10}}'
```

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"maintenance_operator","tool":"promote_ready_jobs","tool_args":{"limit":10}}'
```

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"maintenance_operator","tool":"recover_workflow","tool_args":{"workflow_id":"<workflow_id>","reclaim_expired_jobs":true,"reschedule_failed_jobs":true}}'
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

```bash
curl -i -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent":"researcher","tool":"promote_ready_jobs","tool_args":{"limit":5}}'
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

`v1.1` is complete. The next planned milestone lives in `docs/roadmap.md` and is `v1.2` assistant deployment hardening, which turns the new assistant surfaces into a narrower deployable profile.

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

`v1.6` is the current release. `v1.7` is now the next milestone, focused on deployment and operator maturity.

### `v1.1` Acceptance Criteria

- ClarityOS supports explicit user conversation/session records that map into workflows, memory, and operator-visible history.
- A first assistant surface exists, ideally web-first, that uses the existing runtime instead of introducing a second execution path.
- Operators can inspect live conversations, related workflows, and recovery actions through a simple UI.
- Any first channel adapter remains thin and transport-focused, with workflow, queue, memory, and recovery behavior still owned by the runtime core.

`v1.1` completion snapshot:

- Slice 1 complete: persisted sessions, `/sessions` endpoints, session-to-workflow mapping, and session control-plane summaries
- Slice 2 complete: `/assistant` and `/assistant/sessions/{session_id}` provide a thin browser surface over the existing session runtime
- Slice 3 complete: `/operator` and `/operator/dashboard` provide a thin operator console with session activity, workflow/incident inspection, queue and worker health, and recovery actions
- Slice 4 complete: `/widget`, `/widget.js`, and `/widget/config` provide the first thin external gateway as an embeddable web widget with origin controls and branding defaults
- Still intentionally out of scope: Telegram, Slack, multi-channel routing, hosted transport relays, and marketplace/plugin sprawl

### `v1.2` Acceptance Criteria

- Assistant-facing sessions have explicit ownership and token-backed access rather than relying on shared session ids.
- The widget has an explicit deployment posture around enable/disable state, allowed origins, allowed agents, branding defaults, and launcher behavior.
- Operators have concrete assistant-surface playbooks for incidents, widget deployment mistakes, and session cleanup.
- One narrow browser-first deployed assistant path is defined, supportable, and measurable before broader channel expansion.

`v1.2` completion snapshot:

- Slice 1 complete: assistant-facing sessions now use explicit session ownership and `X-Session-Token` rather than implicit shared access
- Slice 2 complete: the widget now has deployable embed posture with allowed origins, allowed agents, launcher configuration, branding defaults, and fail-closed behavior
- Slice 3 complete: operators can archive and prune sessions, and have dedicated playbooks for assistant incidents, widget deployment, and session cleanup
- Slice 4 complete: `docs/v1.2-release-path.md` defines the first narrow deployed assistant profile and its release gates
- Still intentionally out of scope: Telegram, Slack, hosted hub behavior, multi-tenant browser delivery, and broad channel sprawl

### `v1.3` Acceptance Criteria

- Browser-first assistant questions are more grounded and less generic than the `v1.2` baseline.
- Tool-guided grounding stays explicit and policy-aware rather than hidden or broad.
- Final answers are more structured and easier to scan for planning, comparison, and status questions.
- Browser surfaces are easier to trust because their loading, empty, error, and session states are clearer.
- One narrow browser-first assistant-quality path is documented and measurably better before broader assistant-platform expansion.

`v1.3` completion snapshot:

- Slice 1 complete: assistant surfaces inject repo and roadmap grounding with stronger structured-answer guidance
- Slice 2 complete: guarded tool-guided grounding now uses safe repo/runtime retrieval, controlled fetches, and stronger working-answer framing
- Slice 3 complete: `/assistant`, `/operator`, and `/widget` now have smoke validation plus clearer loading, empty, error, and session-state behavior
- Slice 4 complete: `docs/v1.3-release-path.md` defines the narrow supported use cases and measurable quality gates for the milestone
- Still intentionally out of scope: many-channel expansion, broad arbitrary web research, plugin marketplace behavior, and unrestricted execution
