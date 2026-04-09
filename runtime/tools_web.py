import json
from html.parser import HTMLParser
from urllib import error, request

from runtime.tool_support import normalize_limit, normalize_url, truncate_text, url_domain


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.in_title = False
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        _ = attrs
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if not stripped:
            return
        self.parts.append(stripped)
        if self.in_title:
            self.title_parts.append(stripped)

    @property
    def text(self) -> str:
        return "\n".join(self.parts)

    @property
    def title(self) -> str | None:
        if not self.title_parts:
            return None
        return " ".join(self.title_parts)


def decode_http_body(response, body: bytes) -> str:
    charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace")


def html_to_text_and_title(content: str) -> tuple[str, str | None]:
    parser = _HTMLTextExtractor()
    parser.feed(content)
    return parser.text, parser.title


def fetch_url_tool(args: dict) -> dict:
    url = normalize_url(args.get("url"))
    max_chars = normalize_limit(args.get("max_chars"), field_name="fetch_url.max_chars", default=3000, maximum=12000)
    timeout_seconds = normalize_limit(
        args.get("timeout_seconds"),
        field_name="fetch_url.timeout_seconds",
        default=10,
        maximum=30,
    )

    http_request = request.Request(
        url,
        headers={
            "User-Agent": "ClarityOS/1.2 (+https://github.com/cpgrant/clarityos)",
            "Accept": "text/plain,text/html,application/json",
        },
        method="GET",
    )

    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "")
            raw_body = response.read()
            status_code = getattr(response, "status", 200)
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP error ({exc.code}) fetching {url}: {message}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Could not fetch {url}: {exc.reason}") from exc

    body = decode_http_body(response, raw_body)
    title = None
    normalized_content_type = content_type.lower()
    if "html" in normalized_content_type:
        body, title = html_to_text_and_title(body)
    elif "json" in normalized_content_type:
        try:
            parsed = json.loads(body)
            body = json.dumps(parsed, indent=2, ensure_ascii=True)
        except json.JSONDecodeError:
            pass
    elif "text" not in normalized_content_type:
        raise ValueError(
            f"Tool `fetch_url` only supports text-like responses, got Content-Type `{content_type}`"
        )

    content = body.strip()
    original_content = content
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + "..."

    return {
        "url": url,
        "domain": url_domain(url),
        "status_code": status_code,
        "content_type": content_type,
        "title": title,
        "content_length": len(original_content),
        "content_preview": truncate_text(original_content, limit=240),
        "summary": truncate_text((title + ": " if title else "") + original_content, limit=240),
        "content": content,
        "truncated": len(original_content) > len(content),
    }
