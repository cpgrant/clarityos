def build_prompt(user_input: str, config: dict) -> str:
    system = config.get("system", "")

    return f"""SYSTEM:
{system}

USER:
{user_input}
"""
