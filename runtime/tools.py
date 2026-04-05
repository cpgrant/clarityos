def echo_tool(args: dict) -> str:
    text = args.get("text", "")
    if not isinstance(text, str):
        raise ValueError("Tool `echo` requires `text` to be a string")

    return text


TOOLS = {
    "echo": echo_tool,
}


def list_tools() -> list[str]:
    return sorted(TOOLS)


def call_tool(name: str, args: dict | None = None) -> dict:
    if name not in TOOLS:
        raise ValueError(f"Unknown tool: {name}")

    if args is None:
        args = {}

    if not isinstance(args, dict):
        raise ValueError("Tool arguments must be an object")

    output = TOOLS[name](args)
    return {
        "name": name,
        "args": args,
        "output": output,
        "ok": True,
    }
