from fnmatch import fnmatch

from runtime.tool_support import (
    normalize_limit,
    normalize_path_pattern,
    repo_relative_path,
    resolve_repo_path,
    truncate_text,
)


def read_file_tool(args: dict) -> str:
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Tool `read_file` requires `path` to be a non-empty string")

    file_path = resolve_repo_path(raw_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {raw_path}")

    return file_path.read_text(encoding="utf-8")


def list_files_tool(args: dict) -> dict:
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Tool `list_files` requires `path` to be a non-empty string")

    base_path = resolve_repo_path(raw_path)
    if not base_path.exists():
        raise FileNotFoundError(f"File not found: {raw_path}")
    if not base_path.is_dir():
        raise ValueError(f"Tool `list_files` requires a directory path: {raw_path}")

    pattern = normalize_path_pattern(args.get("pattern"))
    limit = normalize_limit(args.get("limit"), field_name="list_files.limit", default=200, maximum=1000)

    files = []
    file_previews = []
    scanned_file_count = 0
    for candidate in sorted(base_path.rglob("*")):
        if not candidate.is_file():
            continue
        scanned_file_count += 1
        relative = candidate.relative_to(base_path).as_posix()
        if not fnmatch(relative, pattern) and not fnmatch(candidate.name, pattern):
            continue
        repo_path = repo_relative_path(candidate)
        files.append(repo_path)
        file_previews.append(
            {
                "path": repo_path,
                "name": candidate.name,
                "parent": repo_relative_path(candidate.parent),
            }
        )
        if len(files) >= limit:
            break

    return {
        "path": repo_relative_path(base_path),
        "pattern": pattern,
        "limit": limit,
        "result_count": len(files),
        "scanned_file_count": scanned_file_count,
        "truncated": scanned_file_count > len(files),
        "file_previews": file_previews[: min(len(file_previews), 20)],
        "files": files,
    }


def list_directory_tool(args: dict) -> dict:
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Tool `list_directory` requires `path` to be a non-empty string")

    base_path = resolve_repo_path(raw_path)
    if not base_path.exists():
        raise FileNotFoundError(f"File not found: {raw_path}")
    if not base_path.is_dir():
        raise ValueError(f"Tool `list_directory` requires a directory path: {raw_path}")

    limit = normalize_limit(args.get("limit"), field_name="list_directory.limit", default=50, maximum=200)

    directories = 0
    files = 0
    entries = []
    for candidate in sorted(base_path.iterdir()):
        if candidate.is_dir():
            directories += 1
            entry_type = "directory"
        elif candidate.is_file():
            files += 1
            entry_type = "file"
        else:
            entry_type = "other"

        if len(entries) >= limit:
            continue

        entries.append(
            {
                "name": candidate.name,
                "path": repo_relative_path(candidate),
                "entry_type": entry_type,
            }
        )

    return {
        "path": repo_relative_path(base_path),
        "limit": limit,
        "entry_count": directories + files,
        "directory_count": directories,
        "file_count": files,
        "truncated": directories + files > len(entries),
        "entries": entries,
        "summary": f"{repo_relative_path(base_path)} contains {directories} directories and {files} files",
    }


def read_file_range_tool(args: dict) -> dict:
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Tool `read_file_range` requires `path` to be a non-empty string")

    start_line = args.get("start_line")
    if not isinstance(start_line, int) or start_line <= 0:
        raise ValueError("Tool `read_file_range` requires `start_line` to be a positive integer")

    end_line = args.get("end_line", start_line)
    if not isinstance(end_line, int) or end_line <= 0:
        raise ValueError("Tool `read_file_range` requires `end_line` to be a positive integer")
    if end_line < start_line:
        raise ValueError("Tool `read_file_range` requires `end_line` to be >= `start_line`")

    file_path = resolve_repo_path(raw_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {raw_path}")

    lines = file_path.read_text(encoding="utf-8").splitlines()
    selected = lines[start_line - 1 : end_line]
    return {
        "path": repo_relative_path(file_path),
        "start_line": start_line,
        "end_line": end_line,
        "line_count": len(selected),
        "total_line_count": len(lines),
        "content_preview": truncate_text("\n".join(selected), limit=240),
        "content": "\n".join(selected),
    }


def search_files_tool(args: dict) -> dict:
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Tool `search_files` requires `path` to be a non-empty string")

    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Tool `search_files` requires `query` to be a non-empty string")

    base_path = resolve_repo_path(raw_path)
    if not base_path.exists():
        raise FileNotFoundError(f"File not found: {raw_path}")
    if not base_path.is_dir():
        raise ValueError(f"Tool `search_files` requires a directory path: {raw_path}")

    pattern = normalize_path_pattern(args.get("pattern"))
    limit = normalize_limit(args.get("limit"), field_name="search_files.limit", default=20, maximum=200)
    normalized_query = query.strip()
    hits = []
    matched_files = set()
    files_scanned = 0

    for candidate in sorted(base_path.rglob("*")):
        if not candidate.is_file():
            continue
        files_scanned += 1
        relative = candidate.relative_to(base_path).as_posix()
        if not fnmatch(relative, pattern) and not fnmatch(candidate.name, pattern):
            continue

        try:
            contents = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for line_number, line in enumerate(contents.splitlines(), start=1):
            if normalized_query not in line:
                continue
            matched_files.add(repo_relative_path(candidate))
            context_before = contents.splitlines()[line_number - 2] if line_number > 1 else None
            context_after = contents.splitlines()[line_number] if line_number < len(contents.splitlines()) else None
            hits.append(
                {
                    "path": repo_relative_path(candidate),
                    "line_number": line_number,
                    "line": line,
                    "match_preview": truncate_text(line.strip(), limit=180),
                    "context_before": truncate_text(context_before, limit=120),
                    "context_after": truncate_text(context_after, limit=120),
                }
            )
            if len(hits) >= limit:
                return {
                    "path": repo_relative_path(base_path),
                    "query": normalized_query,
                    "pattern": pattern,
                    "limit": limit,
                    "result_count": len(hits),
                    "matched_file_count": len(matched_files),
                    "matched_files": sorted(matched_files),
                    "files_scanned": files_scanned,
                    "truncated": True,
                    "hits": hits,
                }

    return {
        "path": repo_relative_path(base_path),
        "query": normalized_query,
        "pattern": pattern,
        "limit": limit,
        "result_count": len(hits),
        "matched_file_count": len(matched_files),
        "matched_files": sorted(matched_files),
        "files_scanned": files_scanned,
        "truncated": False,
        "hits": hits,
    }
