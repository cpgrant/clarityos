import json
import re
from pathlib import Path
from typing import Any


PERSISTED_STATE_VERSION = "v0.9"
STATE_VERSION_PATTERN = re.compile(r"^v(\d+)\.(\d+)$")


def state_envelope(
    payload: dict[str, Any],
    *,
    schema: str,
    version: str = PERSISTED_STATE_VERSION,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Persisted state payload must be an object")
    if not isinstance(schema, str) or not schema.strip():
        raise ValueError("Persisted state schema must be a non-empty string")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Persisted state version must be a non-empty string")

    return {
        "schema": schema.strip(),
        "version": version.strip(),
        "payload": dict(payload),
    }


def parse_state_version(version: str) -> tuple[int, int]:
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Persisted state version must be a non-empty string")
    match = STATE_VERSION_PATTERN.fullmatch(version.strip())
    if match is None:
        raise ValueError(
            f"Persisted state version `{version}` must match `v<major>.<minor>`"
        )
    return int(match.group(1)), int(match.group(2))


def is_supported_state_version(
    version: str,
    *,
    current_version: str = PERSISTED_STATE_VERSION,
) -> bool:
    return parse_state_version(version) <= parse_state_version(current_version)


def write_state_payload(
    path: Path,
    payload: dict[str, Any],
    *,
    schema: str,
    version: str = PERSISTED_STATE_VERSION,
) -> dict[str, Any]:
    envelope = state_envelope(payload, schema=schema, version=version)
    with path.open("w", encoding="utf-8") as file:
        json.dump(envelope, file, indent=2)
    return dict(payload)


def unwrap_state_payload(data: Any, *, schema: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Persisted state file must contain an object")

    if {"schema", "version", "payload"}.issubset(data):
        if data["schema"] != schema:
            raise ValueError(
                f"Persisted state schema mismatch: expected `{schema}`, got `{data['schema']}`"
            )
        version = data["version"]
        if not is_supported_state_version(version):
            raise ValueError(
                f"Persisted state version `{version}` is newer than supported version `{PERSISTED_STATE_VERSION}`"
            )
        payload = data["payload"]
        if not isinstance(payload, dict):
            raise ValueError("Persisted state payload must be an object")
        return dict(payload)

    # Backward compatibility for pre-v0.9 raw JSON snapshots.
    return dict(data)


def load_state_payload(path: Path, *, schema: str) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return unwrap_state_payload(json.load(file), schema=schema)


def inspect_state_payload(
    path: Path,
    *,
    schema: str,
    include_payload: bool = False,
) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("Persisted state file must contain an object")

    if {"schema", "version", "payload"}.issubset(data):
        version = data["version"]
        parse_state_version(version)
        payload = data["payload"]
        if not isinstance(payload, dict):
            raise ValueError("Persisted state payload must be an object")
        inspection = {
            "schema": data["schema"],
            "expected_schema": schema,
            "version": version,
            "current_version": PERSISTED_STATE_VERSION,
            "legacy_format": False,
            "supported": data["schema"] == schema and is_supported_state_version(version),
            "payload_keys": sorted(payload.keys()),
        }
        if include_payload:
            inspection["payload"] = dict(payload)
        return inspection

    inspection = {
        "schema": None,
        "expected_schema": schema,
        "version": None,
        "current_version": PERSISTED_STATE_VERSION,
        "legacy_format": True,
        "supported": True,
        "payload_keys": sorted(data.keys()),
    }
    if include_payload:
        inspection["payload"] = dict(data)
    return inspection


def migrate_state_payload(
    path: Path,
    *,
    schema: str,
    target_version: str = PERSISTED_STATE_VERSION,
) -> dict[str, Any]:
    inspection_before = inspect_state_payload(path, schema=schema, include_payload=True)

    if not inspection_before["legacy_format"]:
        if inspection_before["schema"] != schema:
            raise ValueError(
                f"Persisted state schema mismatch: expected `{schema}`, got `{inspection_before['schema']}`"
            )
        if not is_supported_state_version(inspection_before["version"], current_version=target_version):
            raise ValueError(
                f"Persisted state version `{inspection_before['version']}` is newer than supported version `{target_version}`"
            )
        inspection_after = dict(inspection_before)
        inspection_after.pop("payload", None)
        inspection_before["migrated"] = False
        return {
            "migrated": False,
            "before": inspection_before,
            "after": inspection_after,
        }

    payload = inspection_before["payload"]
    write_state_payload(path, payload, schema=schema, version=target_version)
    inspection_after = inspect_state_payload(path, schema=schema, include_payload=False)
    inspection_before["migrated"] = True
    return {
        "migrated": True,
        "before": inspection_before,
        "after": inspection_after,
    }


def migrate_state_directory(
    directory: Path,
    *,
    schema: str,
    target_version: str = PERSISTED_STATE_VERSION,
    limit: int | None = None,
    include_unchanged: bool = False,
) -> dict[str, Any]:
    if limit is not None and (not isinstance(limit, int) or limit <= 0):
        raise ValueError("State migration `limit` must be a positive integer")

    if not directory.is_dir():
        return {
            "processed_count": 0,
            "migrated_count": 0,
            "unchanged_count": 0,
            "results": [],
        }

    paths = sorted(directory.glob("*.json"))
    if limit is not None:
        paths = paths[:limit]

    results = []
    migrated_count = 0
    unchanged_count = 0
    for path in paths:
        result = migrate_state_payload(path, schema=schema, target_version=target_version)
        if result["migrated"]:
            migrated_count += 1
        else:
            unchanged_count += 1
        if include_unchanged or result["migrated"]:
            results.append(
                {
                    "state_id": path.stem,
                    **result,
                }
            )

    return {
        "processed_count": len(paths),
        "migrated_count": migrated_count,
        "unchanged_count": unchanged_count,
        "results": results,
    }
