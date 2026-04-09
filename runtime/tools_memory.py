from runtime.memory import create_memory, query_memories


def memory_write_tool(args: dict) -> dict:
    memory_type = args.get("memory_type")
    payload = args.get("payload")
    scope_kind = args.get("scope_kind", "agent")
    agent = args.get("agent")
    workflow_id = args.get("workflow_id")
    run_id = args.get("run_id")
    tags = args.get("tags")
    metadata = args.get("metadata")

    return create_memory(
        memory_type=memory_type,
        payload=payload,
        scope_kind=scope_kind,
        agent=agent,
        workflow_id=workflow_id,
        run_id=run_id,
        tags=tags,
        metadata=metadata,
    )


def memory_query_tool(args: dict) -> dict:
    scope_kind = args.get("scope_kind")
    if not isinstance(scope_kind, str) or not scope_kind.strip():
        raise ValueError("Tool `memory_query` requires `scope_kind` to be a non-empty string")

    return query_memories(
        query=args.get("query", ""),
        memory_type=args.get("memory_type"),
        scope_kind=scope_kind,
        agent=args.get("agent"),
        workflow_id=args.get("workflow_id"),
        run_id=args.get("run_id"),
        tags=args.get("tags"),
        limit=args.get("limit", 5),
        max_chars=args.get("max_chars", 1200),
        max_summary_chars=args.get("max_summary_chars", 240),
    )
