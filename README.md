# ClarityOS

Minimal, explicit LLM execution runtime.

## Status

- Current release: `v0.3`
- Current focus: explicit tools with structured traces and API errors
- Next target: `v0.4` - control and safety

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
├── api/
│   └── main.py
├── config/
│   ├── agents.yaml
│   └── models.yaml
├── logs/
├── runtime/
│   ├── agent.py
│   ├── model.py
│   ├── prompt_builder.py
│   ├── trace.py
│   └── tools.py
├── scripts/
│   └── show_latest_log.sh
├── tests/
│   ├── test_agent.py
│   └── test_api.py
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

Run the default agent:

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

The `/run` response returns:

- `status`
- `run_type`
- `agent`
- `prompt`
- `provider`
- `model`
- `tool`
- `tool_args`
- `tool_output`
- `output`

For tool runs, invalid requests return structured JSON errors with HTTP `400` or `404` instead of a generic internal server error.

## Logs

Each run creates:

```text
logs/run_<timestamp>.json
```

Model-run success log example:

```json
{
  "version": "v0.3",
  "timestamp": "...",
  "run_id": "...",
  "run_type": "model",
  "status": "success",
  "duration_ms": 12.3,
  "input": "...",
  "agent": "...",
  "prompt": "...",
  "model_alias": "fast",
  "provider": "openai",
  "model": "gpt-4o-mini",
  "output": "..."
}
```

Tool-run success log example:

```json
{
  "version": "v0.3",
  "timestamp": "...",
  "run_id": "...",
  "run_type": "tool",
  "status": "success",
  "duration_ms": 1.2,
  "input": "",
  "agent": "default",
  "prompt": null,
  "model_alias": null,
  "tool_name": "read_file",
  "tool_args": {
    "path": "README.md"
  },
  "tool_output": "...file contents...",
  "tool_ok": true,
  "output": "...file contents..."
}
```

Tool-run error logs include:

```json
{
  "version": "v0.3",
  "run_type": "tool",
  "status": "error",
  "tool_name": "read_file",
  "tool_args": {
    "path": "../.bashrc"
  },
  "error_type": "...",
  "error_message": "...",
  "tool_error": "..."
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
- trace creation
- explicit tool execution
- API error mapping

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
- `v0.5` - workflows
- `v0.6` - queues and jobs
- `v0.7` - memory and retrieval
- `v0.8` - multi-agent coordination
- `v0.9` - production hardening
