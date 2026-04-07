import json
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
TRACE_VERSION = "v0.7"
TRACE_SCHEMA = "trace.v2"


def trace_run(data: dict) -> Path:
    LOG_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now(timezone.utc)
    filename_timestamp = timestamp.isoformat().replace(":", "-")
    log_path = LOG_DIR / f"run_{filename_timestamp}.json"

    trace_payload = {
        "version": TRACE_VERSION,
        "schema": TRACE_SCHEMA,
        "timestamp": timestamp.isoformat(),
        **data,
    }

    with log_path.open("w", encoding="utf-8") as file:
        json.dump(trace_payload, file, indent=2)

    return log_path
