from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import urlparse

from runtime.agent import load_agent
from runtime.policy import PolicyAction, build_agent_policy, evaluate_policy
from runtime.tools import call_tool
from runtime.tools import get_tool_definition


BASE_DIR = Path(__file__).resolve().parent.parent
README_PATH = BASE_DIR / "README.md"
ROADMAP_PATH = BASE_DIR / "docs" / "roadmap.md"
HISTORY_DIR = BASE_DIR / "docs" / "history"
GROUNDING_SURFACES = {"assistant_web", "embed_widget"}
PROJECT_KEYWORDS = {
    "clarityos",
    "roadmap",
    "milestone",
    "version",
    "workflow",
    "workflows",
    "session",
    "sessions",
    "operator",
    "widget",
    "assistant",
    "openclaw",
    "crewai",
    "react",
    "multi-agent",
    "multi agent",
    "runtime",
    "deployment",
    "release",
    "tool",
    "tools",
    "memory",
    "queue",
    "worker",
    "objective",
    "goal",
    "gaps",
    "gap",
    "compare",
    "comparison",
    "architecture",
    "where are we",
    "what's next",
    "whats next",
}
EXTERNAL_FETCH_KEYWORDS = {
    "openclaw": "https://docs.openclaw.ai/",
    "openai": "https://platform.openai.com/docs/overview",
    "crewai": "https://docs.crewai.com/",
}
STRUCTURED_KEYWORDS = {
    "compare",
    "comparison",
    "gap",
    "gaps",
    "roadmap",
    "plan",
    "next",
    "objective",
    "goal",
    "where are we",
    "what is the objective",
    "openclaw",
    "crewai",
    "react",
    "architecture",
    "version",
    "milestone",
}
COMPARISON_KEYWORDS = {
    "compare",
    "comparison",
    "gap",
    "gaps",
    "versus",
    "vs",
    "better",
    "similar",
    "equal",
    "difference",
    "openclaw",
    "crewai",
    "react",
}
PLANNING_KEYWORDS = {
    "plan",
    "roadmap",
    "next",
    "milestone",
    "priority",
    "prioritize",
    "slice",
    "release",
    "v1.",
}
SUMMARY_KEYWORDS = {
    "summarize",
    "summary",
    "summarise",
    "briefly",
    "what did",
    "what changed",
    "what improved",
    "what was accomplished",
}
STATUS_KEYWORDS = {
    "where are we",
    "current",
    "status",
    "objective",
    "goal",
    "what's next",
    "whats next",
}
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
VERSION_PATTERN = re.compile(r"\bv\d+\.\d+(?:\.\d+)?\b", flags=re.IGNORECASE)
RUNTIME_KEYWORDS = {
    "workflow",
    "workflows",
    "session",
    "sessions",
    "queue",
    "worker",
    "workers",
    "tool",
    "tools",
    "runtime",
    "operator",
    "memory",
    "trace",
}
UI_KEYWORDS = {
    "assistant",
    "widget",
    "operator",
    "ui",
    "webui",
    "web",
    "embed",
}
STOP_WORDS = {
    "what",
    "which",
    "where",
    "when",
    "why",
    "how",
    "does",
    "is",
    "are",
    "the",
    "this",
    "that",
    "with",
    "from",
    "into",
    "about",
    "would",
    "could",
    "should",
    "have",
    "has",
    "been",
    "like",
    "system",
    "project",
}
MAX_GROUNDED_EXCERPTS = 4


def assistant_surface_grounding_enabled(surface: str | None) -> bool:
    return isinstance(surface, str) and surface in GROUNDING_SURFACES


def looks_like_project_question(user_input: str) -> bool:
    lowered = user_input.lower()
    return any(keyword in lowered for keyword in PROJECT_KEYWORDS)


def _extract_readme_status_section() -> str:
    text = README_PATH.read_text(encoding="utf-8")
    lines = []
    for line in text.splitlines():
        if line.startswith("## Historical Docs"):
            break
        lines.append(line)
    return "\n".join(line for line in lines if line.strip()).strip()


def _extract_roadmap_summary() -> str:
    text = ROADMAP_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    current_status = []
    in_current_status = False
    for line in lines:
        if line.startswith("## Current Status"):
            in_current_status = True
            continue
        if in_current_status and line.startswith("## "):
            break
        if in_current_status and line.strip():
            current_status.append(line)

    proposed = []
    for match in re.finditer(r"^\d+\.\s+`(v1\.[3-9])`\s+-\s+(.+)$", text, flags=re.MULTILINE):
        proposed.append(f"- {match.group(1)}: {match.group(2)}")

    sections = []
    if current_status:
        sections.append("Current roadmap status:\n" + "\n".join(current_status))
    if proposed:
        sections.append("Proposed next roadmap:\n" + "\n".join(proposed))
    return "\n\n".join(sections).strip()


@lru_cache(maxsize=1)
def repo_grounding_context() -> list[dict[str, str]]:
    return [
        {
            "title": "ClarityOS repository status",
            "source": "README.md",
            "content": _extract_readme_status_section(),
        },
        {
            "title": "ClarityOS roadmap summary",
            "source": "docs/roadmap.md",
            "content": _extract_roadmap_summary(),
        },
    ]


def extract_markdown_section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    collected: list[str] = []
    in_section = False
    heading_line = f"## {heading}"
    for line in lines:
        if line.startswith(heading_line):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.strip():
            collected.append(line)
    return "\n".join(collected).strip()


def mentioned_versions(user_input: str) -> list[str]:
    seen: list[str] = []
    for match in VERSION_PATTERN.findall(user_input):
        version = match.lower()
        if version not in seen:
            seen.append(version)
    return seen


def milestone_history_context(user_input: str) -> list[dict[str, str]]:
    context: list[dict[str, str]] = []
    modes = question_modes(user_input)
    for version in mentioned_versions(user_input)[:2]:
        history_path = HISTORY_DIR / f"{version}.md"
        if not history_path.exists():
            continue
        added = extract_markdown_section(history_path, f"What {version} Added")
        if added:
            context.append(
                {
                    "title": f"{version} shipped changes",
                    "source": f"docs/history/{version}.md",
                    "content": added,
                }
            )
        if "summary" in modes or "status" in modes:
            supported = extract_markdown_section(history_path, "Supported Shape")
            if supported:
                context.append(
                    {
                        "title": f"{version} supported shape",
                        "source": f"docs/history/{version}.md#supported-shape",
                        "content": supported,
                    }
                )
    return context


def answer_guidance(user_input: str) -> str:
    lowered = user_input.lower()
    modes = question_modes(user_input)
    if modes or any(keyword in lowered for keyword in STRUCTURED_KEYWORDS):
        return (
            "Ground the answer in the supplied project context and avoid generic software advice. "
            "Prefer short structured sections or bullets. Name concrete shipped changes instead of abstract themes. "
            "Answer the question that was asked, and do not jump to future milestones unless the user asked for them. "
            "When relevant, cover current state, gaps, and the next recommendation. If the supplied context is insufficient, say what is missing."
        )
    return (
        "Ground the answer in the supplied project context, keep it concise, answer the asked question directly, "
        "and avoid generic unsupported claims."
    )


def question_modes(user_input: str) -> set[str]:
    lowered = user_input.lower()
    modes: set[str] = set()
    if any(keyword in lowered for keyword in SUMMARY_KEYWORDS):
        modes.add("summary")
    if any(keyword in lowered for keyword in COMPARISON_KEYWORDS):
        modes.add("comparison")
    if any(keyword in lowered for keyword in PLANNING_KEYWORDS):
        modes.add("plan")
    if any(keyword in lowered for keyword in STATUS_KEYWORDS):
        modes.add("status")
    if not modes and any(keyword in lowered for keyword in STRUCTURED_KEYWORDS):
        modes.add("structured")
    return modes


def answer_structure_hint(user_input: str) -> dict[str, str] | None:
    modes = question_modes(user_input)
    if not modes:
        return None

    if "comparison" in modes and "plan" in modes:
        content = (
            "Use this answer shape:\n"
            "- Current position: where ClarityOS stands now in the compared area\n"
            "- Similarities: the strongest overlaps worth naming\n"
            "- Gaps: the main missing capabilities or weaker areas\n"
            "- Next milestone priority: the smallest next move that closes the most important gap"
        )
    elif "comparison" in modes:
        content = (
            "Use this answer shape:\n"
            "- Current position: the short bottom line first\n"
            "- Similarities: where the systems are meaningfully alike\n"
            "- Gaps: what ClarityOS still lacks or does differently\n"
            "- Recommendation: what to prioritize next"
        )
    elif "summary" in modes:
        content = (
            "Use this answer shape:\n"
            "- Bottom line: one sentence on what changed\n"
            "- Concrete improvements: 3 to 5 specific shipped changes\n"
            "- User-visible impact: why those changes matter in practice\n"
            "- Keep the answer on the asked milestone unless future milestones were explicitly requested"
        )
    elif "plan" in modes:
        content = (
            "Use this answer shape:\n"
            "- Objective: what the milestone is trying to achieve\n"
            "- Current state: what already exists in the repo\n"
            "- Next slices: the best ordered next moves\n"
            "- Out of scope: what should not be chased yet"
        )
    elif "status" in modes:
        content = (
            "Use this answer shape:\n"
            "- Objective\n"
            "- Where we are now\n"
            "- What is working\n"
            "- What should happen next"
        )
    else:
        content = (
            "Use a short structured answer with a clear bottom line first, then grounded supporting points."
        )
    return {
        "title": "Suggested answer structure",
        "source": "answer_structure",
        "content": content,
    }


def extract_query_terms(user_input: str) -> list[str]:
    lowered = user_input.lower()
    prioritized = []
    for keyword in sorted(PROJECT_KEYWORDS, key=len, reverse=True):
        if keyword in lowered and keyword not in prioritized:
            prioritized.append(keyword)
        if len(prioritized) >= 3:
            return prioritized

    fallback = list(prioritized)
    for token in re.findall(r"[a-zA-Z0-9_.-]+", lowered):
        if len(token) < 5 or token in STOP_WORDS or token in fallback:
            continue
        if token not in fallback:
            fallback.append(token)
        if len(fallback) >= 3:
            break
    return fallback


def repo_search_specs(user_input: str) -> list[dict[str, str]]:
    lowered = user_input.lower()
    specs = [{"path": ".", "pattern": "*.md"}]
    if any(keyword in lowered for keyword in RUNTIME_KEYWORDS):
        specs.append({"path": "runtime", "pattern": "*.py"})
    if any(keyword in lowered for keyword in UI_KEYWORDS):
        specs.append({"path": "ui", "pattern": "*.html"})
    return specs


def normalize_excerpt_content(content: str) -> str:
    stripped = content.strip()
    if len(stripped) <= 500:
        return stripped
    return stripped[:497].rstrip() + "..."


def tool_domain(tool_args: dict, *, domain_arg: str | None) -> str | None:
    if not isinstance(domain_arg, str) or not domain_arg:
        return None
    raw_value = tool_args.get(domain_arg)
    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    parsed = urlparse(raw_value.strip())
    return (parsed.hostname or parsed.netloc or None)


def tool_permitted_for_agent(agent_name: str, tool_name: str, tool_args: dict) -> bool:
    agent_config = load_agent(agent_name)
    allowed_tools = agent_config.get("tools", [])
    if tool_name not in allowed_tools:
        return False

    tool_definition = get_tool_definition(tool_name)
    action = PolicyAction(
        capability=tool_definition["capability"],
        path=tool_args.get(tool_definition.get("path_arg", "")),
        domain=tool_domain(tool_args, domain_arg=tool_definition.get("domain_arg")),
        command=tool_definition.get("command"),
        memory_type=tool_args.get("memory_type"),
        scope_kind=tool_args.get("scope_kind"),
    )
    decision = evaluate_policy(build_agent_policy(agent_config), action)
    return decision.allowed


def guarded_tool_call(agent_name: str, tool_name: str, tool_args: dict) -> dict | None:
    if not tool_permitted_for_agent(agent_name, tool_name, tool_args):
        return None
    result = call_tool(tool_name, tool_args)
    if not result.get("ok"):
        return None
    return result


def summarize_session_inspection(view: dict) -> str:
    summary = view.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary
    session_info = view.get("session", {})
    workflow = view.get("current_workflow") or {}
    continuity = view.get("continuity") or {}
    return "\n".join(
        [
            f"Session status: {session_info.get('status')}",
            f"Agent: {session_info.get('agent')}",
            f"Current workflow: {session_info.get('current_workflow_id')}",
            f"Workflow count: {session_info.get('workflow_count')}",
            f"Message count: {session_info.get('message_count')}",
            f"Current workflow status: {workflow.get('status')}",
            f"Current step: {workflow.get('current_step')}",
            f"Recent continuity memories: {continuity.get('recent_count')}",
        ]
    )


def summarize_workflow_inspection(view: dict) -> str:
    summary = view.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary
    workflow = view.get("workflow", {})
    current_step = view.get("current_step") or {}
    incident = view.get("incident") or {}
    return "\n".join(
        [
            f"Workflow status: {workflow.get('status')}",
            f"Agent: {workflow.get('agent')}",
            f"Run type: {workflow.get('run_type')}",
            f"Current step: {current_step.get('step_type')} ({current_step.get('status')})",
            f"Failure summary: {view.get('failure')}",
            f"Incident rollup: {incident.get('rollup')}",
        ]
    )


def runtime_identifier_context(agent_name: str, user_input: str) -> list[dict[str, str]]:
    lowered = user_input.lower()
    ids = UUID_PATTERN.findall(user_input)
    if not ids:
        return []

    context = []
    seen = set()
    for identifier in ids[:2]:
        if "session" in lowered and ("session", identifier) not in seen:
            result = guarded_tool_call(agent_name, "inspect_session", {"session_id": identifier})
            if result is not None:
                context.append(
                    {
                        "title": "Session inspection summary",
                        "source": f"inspect_session:{identifier}",
                        "content": summarize_session_inspection(result["output"]["value"]),
                    }
                )
                seen.add(("session", identifier))
        if "workflow" in lowered and ("workflow", identifier) not in seen:
            result = guarded_tool_call(agent_name, "inspect_workflow", {"workflow_id": identifier})
            if result is not None:
                context.append(
                    {
                        "title": "Workflow inspection summary",
                        "source": f"inspect_workflow:{identifier}",
                        "content": summarize_workflow_inspection(result["output"]["value"]),
                    }
                )
                seen.add(("workflow", identifier))
    return context


def external_fetch_context(agent_name: str, user_input: str) -> list[dict[str, str]]:
    lowered = user_input.lower()
    context = []
    for keyword, url in EXTERNAL_FETCH_KEYWORDS.items():
        if keyword not in lowered:
            continue
        result = guarded_tool_call(agent_name, "fetch_url", {"url": url, "max_chars": 1200})
        if result is None:
            continue
        value = result["output"]["value"]
        context.append(
            {
                "title": f"Fetched external reference for `{keyword}`",
                "source": value.get("url", url),
                "content": normalize_excerpt_content(
                    str(value.get("summary") or value.get("content_preview") or value.get("content", ""))
                ),
            }
        )
    return context


def tool_guided_context(agent_name: str, user_input: str) -> list[dict[str, str]]:
    query_terms = extract_query_terms(user_input)
    if not query_terms:
        return []

    excerpts = []
    seen_locations = set()
    for spec in repo_search_specs(user_input):
        for term in query_terms:
            result = guarded_tool_call(
                agent_name,
                "search_files",
                {
                    "path": spec["path"],
                    "query": term,
                    "pattern": spec["pattern"],
                    "limit": 2,
                },
            )
            if result is None:
                continue
            hits = result["output"]["value"].get("hits", [])
            for hit in hits:
                path = hit.get("path")
                line_number = hit.get("line_number")
                if not isinstance(path, str) or not isinstance(line_number, int):
                    continue
                key = (path, line_number)
                if key in seen_locations:
                    continue
                seen_locations.add(key)
                excerpt_result = guarded_tool_call(
                    agent_name,
                    "read_file_range",
                    {
                        "path": path,
                        "start_line": max(1, line_number - 1),
                        "end_line": line_number + 2,
                    },
                )
                if excerpt_result is None:
                    continue
                excerpt = excerpt_result["output"]["value"]
                content = normalize_excerpt_content(str(excerpt.get("content", "")))
                if not content:
                    continue
                header = hit.get("match_preview") or hit.get("line") or term
                excerpts.append(
                    {
                        "title": f"Relevant excerpt for `{header}`",
                        "source": f"{path}:{excerpt['start_line']}-{excerpt['end_line']}",
                        "content": content,
                    }
                )
                if len(excerpts) >= MAX_GROUNDED_EXCERPTS:
                    return excerpts
    return excerpts


def build_grounding_summary(user_input: str, context: list[dict[str, str]]) -> dict[str, str] | None:
    evidence = [
        entry
        for entry in context
        if entry.get("source") not in {"README.md", "docs/roadmap.md", "assistant_profile"}
    ]
    if not evidence:
        return None

    lines = []
    for entry in evidence[:MAX_GROUNDED_EXCERPTS]:
        title = str(entry.get("title", "Context")).strip()
        source = str(entry.get("source", "")).strip()
        content = normalize_excerpt_content(str(entry.get("content", "")))
        if not content:
            continue
        first_line = content.splitlines()[0]
        label = f"{title} [{source}]" if source else title
        lines.append(f"- {label}: {first_line}")

    if not lines:
        return None

    modes = question_modes(user_input)
    if "comparison" in modes:
        guidance = (
            "Use the evidence below to support a comparison-focused answer. Start with the bottom line, "
            "then name the strongest similarities, then the biggest gaps, then the next recommendation."
        )
    elif "summary" in modes:
        guidance = (
            "Use the evidence below to support a concrete summary. Start with the bottom line, "
            "then name the shipped changes directly from the evidence, then explain the practical impact. "
            "Do not drift into future milestones unless the user asked for them."
        )
    elif "plan" in modes:
        guidance = (
            "Use the evidence below to support a plan-focused answer. Start with the objective and current state, "
            "then propose the next slices or priorities."
        )
    elif "status" in modes or any(keyword in user_input.lower() for keyword in STRUCTURED_KEYWORDS):
        guidance = (
            "Use the evidence below to support the final answer. Prefer a concise answer with a short current-state summary, "
            "then key evidence or gaps, then the next recommendation."
        )
    else:
        guidance = "Use the evidence below directly and avoid unsupported generalizations."
    return {
        "title": "Working answer frame",
        "source": "grounding_summary",
        "content": guidance + "\n" + "\n".join(lines),
    }


def build_assistant_prompt_context(
    *,
    surface: str | None,
    user_input: str,
    agent_name: str = "default",
) -> list[dict[str, str]]:
    if not assistant_surface_grounding_enabled(surface):
        return []
    if not looks_like_project_question(user_input):
        return []

    context = [dict(entry) for entry in repo_grounding_context()]
    context.extend(milestone_history_context(user_input))
    context.extend(runtime_identifier_context(agent_name, user_input))
    context.extend(tool_guided_context(agent_name, user_input))
    context.extend(external_fetch_context(agent_name, user_input))
    grounding_summary = build_grounding_summary(user_input, context)
    if grounding_summary is not None:
        context.append(grounding_summary)
    structure_hint = answer_structure_hint(user_input)
    if structure_hint is not None:
        context.append(structure_hint)
    context.append(
        {
            "title": "Answer guidance",
            "source": "assistant_profile",
            "content": answer_guidance(user_input),
        }
    )
    return context
