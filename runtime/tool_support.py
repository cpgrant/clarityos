from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def resolve_repo_path(raw_path: str) -> Path:
    repo_root = BASE_DIR.resolve()
    candidate = Path(raw_path)

    if not candidate.is_absolute():
        candidate = repo_root / candidate

    resolved_path = candidate.resolve()

    try:
        resolved_path.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError("Tool `read_file` only allows files inside the repo") from exc

    return resolved_path


def repo_relative_path(path: Path) -> str:
    return path.resolve().relative_to(BASE_DIR.resolve()).as_posix()


def normalize_limit(value: object, *, field_name: str, default: int, maximum: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"Tool `{field_name}` must be a positive integer")
    return min(value, maximum)


def normalize_path_pattern(value: object) -> str:
    if value is None:
        return "*"
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Tool `pattern` must be a non-empty string when provided")
    return value.strip()


def truncate_text(value: object, *, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def normalize_url(value: object, *, field_name: str = "url") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Tool `{field_name}` must be a non-empty string")
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Tool `fetch_url` requires an absolute http/https URL")
    return url


def url_domain(value: str) -> str:
    parsed = urlparse(value)
    return (parsed.hostname or parsed.netloc).lower()
