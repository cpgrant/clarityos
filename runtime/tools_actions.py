from runtime.tool_support import normalize_limit


def archive_session_tool(args: dict) -> dict:
    from runtime.session import archive_session

    session_id = args.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Tool `archive_session` requires `session_id` to be a non-empty string")

    archived = archive_session(session_id.strip(), reason=args.get("reason"))
    return {
        "summary": f"Archived session {archived['session_id']} with status {archived['status']}",
        "session": archived,
    }


def prune_sessions_tool(args: dict) -> dict:
    from runtime.session import prune_sessions

    statuses = args.get("statuses")
    if statuses is not None:
        if not isinstance(statuses, list) or not all(isinstance(item, str) and item.strip() for item in statuses):
            raise ValueError("Tool `prune_sessions` requires `statuses` to be a list of non-empty strings")

    older_than_hours = args.get("older_than_hours", 168)
    if not isinstance(older_than_hours, int) or older_than_hours <= 0:
        raise ValueError("Tool `prune_sessions` requires `older_than_hours` to be a positive integer")

    limit = args.get("limit")
    if limit is not None:
        limit = normalize_limit(limit, field_name="prune_sessions.limit", default=50, maximum=500)

    result = prune_sessions(
        statuses=statuses,
        older_than_hours=older_than_hours,
        limit=limit,
    )
    return {
        "summary": f"Pruned {result['pruned_count']} sessions older than {older_than_hours} hours",
        **result,
    }


def promote_ready_jobs_tool(args: dict) -> dict:
    from runtime.queue import promote_due_jobs

    limit = args.get("limit")
    if limit is not None:
        limit = normalize_limit(limit, field_name="promote_ready_jobs.limit", default=50, maximum=500)

    result = promote_due_jobs(limit=limit)
    return {
        "summary": f"Promoted {result['promoted_count']} ready jobs",
        **result,
    }


def repair_stale_jobs_tool(args: dict) -> dict:
    from runtime.queue import repair_stale_job_state

    limit = args.get("limit")
    if limit is not None:
        limit = normalize_limit(limit, field_name="repair_stale_jobs.limit", default=50, maximum=500)

    result = repair_stale_job_state(limit=limit)
    return {
        "summary": f"Repaired {result['repaired_count']} stale jobs",
        **result,
    }


def repair_orphaned_workers_tool(args: dict) -> dict:
    from runtime.worker import repair_orphaned_workers

    limit = args.get("limit")
    if limit is not None:
        limit = normalize_limit(limit, field_name="repair_orphaned_workers.limit", default=50, maximum=500)

    result = repair_orphaned_workers(limit=limit)
    return {
        "summary": f"Repaired {result['repaired_count']} orphaned workers",
        **result,
    }


def safe_resume_workflow_tool(args: dict) -> dict:
    from runtime.workflow_runner import safe_resume_workflow

    workflow_id = args.get("workflow_id")
    if not isinstance(workflow_id, str) or not workflow_id.strip():
        raise ValueError("Tool `safe_resume_workflow` requires `workflow_id` to be a non-empty string")

    result = safe_resume_workflow(workflow_id.strip())
    return {
        "summary": f"Safely resumed workflow {workflow_id.strip()}",
        **result,
    }


def replay_workflow_tool(args: dict) -> dict:
    from runtime.workflow_runner import replay_workflow

    workflow_id = args.get("workflow_id")
    if not isinstance(workflow_id, str) or not workflow_id.strip():
        raise ValueError("Tool `replay_workflow` requires `workflow_id` to be a non-empty string")

    result = replay_workflow(workflow_id.strip())
    return {
        "summary": f"Replayed workflow {workflow_id.strip()}",
        **result,
    }


def recover_workflow_tool(args: dict) -> dict:
    from runtime.control_plane import recover_workflow

    workflow_id = args.get("workflow_id")
    if not isinstance(workflow_id, str) or not workflow_id.strip():
        raise ValueError("Tool `recover_workflow` requires `workflow_id` to be a non-empty string")

    result = recover_workflow(
        workflow_id.strip(),
        reclaim_expired_jobs=bool(args.get("reclaim_expired_jobs", False)),
        reschedule_failed_jobs=bool(args.get("reschedule_failed_jobs", False)),
        reschedule_dead_letter_jobs=bool(args.get("reschedule_dead_letter_jobs", False)),
        limit=args.get("limit"),
    )
    return {
        "summary": (
            f"Recovered workflow {workflow_id.strip()} with "
            f"{result['reclaimed_count']} reclaimed and {result['rescheduled_count']} rescheduled jobs"
        ),
        **result,
    }
