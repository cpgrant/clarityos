from typing import Any


def classify_error(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "not_found"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ValueError):
        return "validation_error"
    return "tool_error"


def build_error_envelope(exc: Exception) -> dict[str, Any]:
    failure_type = classify_error(exc)
    return {
        "failure_type": failure_type,
        "error_type": type(exc).__name__,
        "message": str(exc),
        "retryable": failure_type == "timeout",
    }


def build_tool_success(
    name: str,
    args: dict[str, Any],
    output: Any,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": True,
        "input": {
            "args": args,
        },
        "output": {
            "value": output,
        },
        "error": None,
        "metadata": metadata or {},
    }


def build_tool_failure(
    name: str,
    args: dict[str, Any],
    exc: Exception,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": False,
        "input": {
            "args": args,
        },
        "output": None,
        "error": build_error_envelope(exc),
        "metadata": metadata or {},
    }


def exception_from_tool_result(result: dict[str, Any]) -> Exception:
    error = result.get("error") or {}
    failure_type = error.get("failure_type")
    message = error.get("message", "Tool failed")

    if failure_type == "not_found":
        return FileNotFoundError(message)
    if failure_type == "validation_error":
        return ValueError(message)
    if failure_type == "timeout":
        return TimeoutError(message)

    return RuntimeError(message)
