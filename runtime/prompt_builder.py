def build_prompt(user_input: str, config: dict, shared_memories: list[dict] | None = None) -> str:
    system = config.get("system", "")
    shared_memories = shared_memories or []

    shared_memory_section = ""
    if shared_memories:
        lines = []
        for memory in shared_memories:
            scope = memory.get("scope", {})
            scope_label = scope.get("kind", "unknown")
            scope_value = scope.get("value")
            if scope_value:
                scope_label = f"{scope_label}:{scope_value}"
            lines.append(
                f"- [{memory['memory_id']}] {memory.get('memory_type', 'memory')} ({scope_label})"
                f": {memory.get('payload_summary', '')}"
            )
        shared_memory_section = "\nSHARED MEMORY:\n" + "\n".join(lines)

    return f"""SYSTEM:
{system}
{shared_memory_section}

USER:
{user_input}
"""
