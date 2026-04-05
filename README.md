# ClarityOS

Minimal, explicit LLM execution runtime.

## Status

- `v0.1` - execution
- `v0.2` - traceability
- `v0.2.1` - lightweight testing
- `v0.2.2` - multi-provider support (OpenAI + Ollama)

## What It Does

Given an input, ClarityOS:

1. Loads agent config from YAML
2. Builds a prompt
3. Calls a model
4. Returns a response
5. Writes a full execution trace

## Architecture

```text
API -> Agent -> Prompt -> Model -> Response
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
│   └── trace.py
├── scripts/
│   └── show_latest_log.sh
├── tests/
│   └── test_agent.py
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

The `/run` response returns:

- `agent`
- `prompt`
- `provider`
- `model`
- `output`

## Logs

Each run creates:

```text
logs/run_<timestamp>.json
```

Success log example:

```json
{
  "version": "v0.2.2",
  "timestamp": "...",
  "run_id": "...",
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

Error logs include:

```json
{
  "version": "v0.2.2",
  "status": "error",
  "error_type": "...",
  "error_message": "..."
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

## Design Principles

- explicit over implicit
- observable execution
- deterministic testing
- minimal architecture

## Next

`v0.3` - tools
