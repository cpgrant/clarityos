from datetime import datetime, timezone


def echo_tool(args: dict) -> str:
    text = args.get("text", "")
    if not isinstance(text, str):
        raise ValueError("Tool `echo` requires `text` to be a string")

    return text


def get_time_tool(args: dict) -> dict:
    _ = args

    timestamp = datetime.now(timezone.utc)
    return {
        "utc": timestamp.isoformat(),
    }
