import argparse
import json
import os
import time
from typing import Any, Callable

from runtime.worker import (
    DEFAULT_LEASE_SECONDS,
    heartbeat_worker,
    load_worker,
    register_worker,
    repair_orphaned_workers,
    run_next_job,
)

WORKER_NAME_ENV_VAR = "CLARITYCLAW_WORKER_NAME"
LEGACY_WORKER_NAME_ENV_VAR = "CLARITYOS_WORKER_NAME"
WORKER_LEASE_SECONDS_ENV_VAR = "CLARITYCLAW_WORKER_LEASE_SECONDS"
LEGACY_WORKER_LEASE_SECONDS_ENV_VAR = "CLARITYOS_WORKER_LEASE_SECONDS"
WORKER_POLL_SECONDS_ENV_VAR = "CLARITYCLAW_WORKER_POLL_SECONDS"
LEGACY_WORKER_POLL_SECONDS_ENV_VAR = "CLARITYOS_WORKER_POLL_SECONDS"
WORKER_REPAIR_ORPHANS_ENV_VAR = "CLARITYCLAW_WORKER_REPAIR_ORPHANS_ON_START"
LEGACY_WORKER_REPAIR_ORPHANS_ENV_VAR = "CLARITYOS_WORKER_REPAIR_ORPHANS_ON_START"
DEFAULT_POLL_SECONDS = 2


def _first_env_value(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if isinstance(value, str):
            return value
    return None


def _parse_positive_int(value: int | str | None, *, field_name: str, allow_zero: bool = False) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            value = int(value)
        except ValueError as exc:
            raise ValueError(f"`{field_name}` must be an integer") from exc
    if not isinstance(value, int):
        raise ValueError(f"`{field_name}` must be an integer")
    if allow_zero:
        if value < 0:
            raise ValueError(f"`{field_name}` must be zero or greater")
    elif value <= 0:
        raise ValueError(f"`{field_name}` must be greater than zero")
    return value


def _parse_bool_env(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"`{WORKER_REPAIR_ORPHANS_ENV_VAR}` must be one of: 1, 0, true, false, yes, no, on, off"
    )


def run_worker_loop(
    *,
    worker_name: str | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
    max_jobs: int | None = None,
    max_idle_polls: int | None = None,
    repair_orphans_on_start: bool = True,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    lease_seconds = _parse_positive_int(lease_seconds, field_name="lease_seconds") or DEFAULT_LEASE_SECONDS
    poll_seconds = _parse_positive_int(poll_seconds, field_name="poll_seconds", allow_zero=True) or 0
    max_jobs = _parse_positive_int(max_jobs, field_name="max_jobs") if max_jobs is not None else None
    max_idle_polls = (
        _parse_positive_int(max_idle_polls, field_name="max_idle_polls", allow_zero=True)
        if max_idle_polls is not None
        else None
    )

    registered_worker = register_worker(name=worker_name, lease_seconds=lease_seconds)
    repair_snapshot = (
        repair_orphaned_workers() if repair_orphans_on_start else {"repaired_workers": [], "repaired_worker_ids": [], "repaired_count": 0}
    )

    processed_jobs = 0
    idle_polls = 0
    errors: list[dict[str, str]] = []

    while True:
        if max_jobs is not None and processed_jobs >= max_jobs:
            break

        encountered_error = False
        result = None
        try:
            result = run_next_job(registered_worker["worker_id"])
        except Exception as exc:
            encountered_error = True
            errors.append({"type": type(exc).__name__, "message": str(exc)})

        if result is not None:
            processed_jobs += 1
            idle_polls = 0
            continue

        idle_polls += 1
        heartbeat_worker(registered_worker["worker_id"])
        if max_idle_polls is not None and idle_polls >= max_idle_polls:
            break
        if poll_seconds > 0:
            sleep_fn(poll_seconds)
        if encountered_error and max_idle_polls == 0:
            break

    return {
        "worker_id": registered_worker["worker_id"],
        "worker": load_worker(registered_worker["worker_id"]),
        "processed_jobs": processed_jobs,
        "idle_polls": idle_polls,
        "error_count": len(errors),
        "errors": errors[-5:],
        "repair_snapshot": repair_snapshot,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a repeatable ClarityClaw worker loop")
    parser.add_argument(
        "--name",
        default=_first_env_value(WORKER_NAME_ENV_VAR, LEGACY_WORKER_NAME_ENV_VAR) or "packaged-worker",
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=_parse_positive_int(
            _first_env_value(WORKER_LEASE_SECONDS_ENV_VAR, LEGACY_WORKER_LEASE_SECONDS_ENV_VAR)
            or str(DEFAULT_LEASE_SECONDS),
            field_name=WORKER_LEASE_SECONDS_ENV_VAR,
        ),
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=_parse_positive_int(
            _first_env_value(WORKER_POLL_SECONDS_ENV_VAR, LEGACY_WORKER_POLL_SECONDS_ENV_VAR)
            or str(DEFAULT_POLL_SECONDS),
            field_name=WORKER_POLL_SECONDS_ENV_VAR,
            allow_zero=True,
        ),
    )
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument("--max-idle-polls", type=int, default=None)
    parser.add_argument(
        "--no-repair-orphans-on-start",
        action="store_true",
        help="Skip orphaned-worker repair before the loop starts",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    repair_orphans_on_start = _parse_bool_env(
        _first_env_value(WORKER_REPAIR_ORPHANS_ENV_VAR, LEGACY_WORKER_REPAIR_ORPHANS_ENV_VAR),
        default=not args.no_repair_orphans_on_start,
    )
    summary = run_worker_loop(
        worker_name=args.name,
        lease_seconds=args.lease_seconds,
        poll_seconds=args.poll_seconds,
        max_jobs=args.max_jobs,
        max_idle_polls=args.max_idle_polls,
        repair_orphans_on_start=repair_orphans_on_start,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
