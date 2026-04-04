#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"

if [[ ! -d "$LOG_DIR" ]]; then
  echo "No logs directory found at $LOG_DIR" >&2
  exit 1
fi

latest_log="$(
  find "$LOG_DIR" -maxdepth 1 -type f -name 'run_*.json' | sort | tail -n 1
)"

if [[ -z "$latest_log" ]]; then
  echo "No run logs found in $LOG_DIR" >&2
  exit 1
fi

echo "Latest log: $latest_log"

if command -v jq >/dev/null 2>&1; then
  jq . "$latest_log"
else
  cat "$latest_log"
fi
