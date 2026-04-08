#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Running targeted trusted-runtime validation drills..."
python -m unittest \
  tests.test_resilience \
  tests.test_release_validation \
  -v

if [[ "${1:-}" == "--full" ]]; then
  echo
  echo "Running full unit suite after targeted drills..."
  python -m unittest discover -s tests -v
fi
