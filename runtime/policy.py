from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

import yaml

from runtime.errors import PolicyDeniedError


BASE_DIR = Path(__file__).resolve().parent.parent
POLICIES_CONFIG_PATH = BASE_DIR / "config" / "policies.yaml"
CAPABILITY_CLASSES = {
    "model_call",
    "file_read",
    "file_write",
    "http",
    "exec",
    "memory_read",
    "memory_write",
}


@dataclass(frozen=True)
class PolicyAction:
    capability: str
    path: str | None = None
    domain: str | None = None
    command: str | None = None
    memory_type: str | None = None
    scope_kind: str | None = None


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str
    matched_scope: str | None


def load_policies() -> dict:
    with POLICIES_CONFIG_PATH.open() as file:
        data = yaml.safe_load(file) or {}

    return data.get("policies", {})


def load_policy(name: str) -> dict:
    policies = load_policies()
    if name not in policies:
        raise ValueError(f"Unknown policy: {name}")

    policy = policies[name] or {}
    return {
        "name": name,
        "allow": list(policy.get("allow", []) or []),
        "approval": list(policy.get("approval", []) or []),
        "deny": list(policy.get("deny", []) or []),
    }


def build_agent_policy(agent_config: dict) -> dict:
    policy_name = agent_config.get("policy")
    if not isinstance(policy_name, str) or not policy_name.strip():
        raise ValueError("Agent is missing required `policy`")

    policy = load_policy(policy_name)
    agent_allow = agent_config.get("allow", []) or []
    agent_approval = agent_config.get("approval", []) or []
    agent_deny = agent_config.get("deny", []) or []

    return {
        "name": policy["name"],
        "allow": [*policy["allow"], *agent_allow],
        "approval": [*policy["approval"], *agent_approval],
        "deny": [*policy["deny"], *agent_deny],
    }


def assert_valid_capability(capability: str) -> None:
    if capability not in CAPABILITY_CLASSES:
        raise ValueError(f"Unknown capability class: {capability}")


def normalize_repo_relative_path(raw_path: str) -> str | None:
    repo_root = BASE_DIR.resolve()
    candidate = Path(raw_path)

    if not candidate.is_absolute():
        candidate = repo_root / candidate

    resolved_path = candidate.resolve()

    try:
        return resolved_path.relative_to(repo_root).as_posix()
    except ValueError:
        return None


def rule_matches(rule: dict, action: PolicyAction) -> tuple[bool, str | None]:
    capability = rule.get("capability")
    if capability != action.capability:
        return False, None

    assert_valid_capability(capability)

    if "paths" in rule:
        if action.path is None:
            return False, None

        normalized_path = normalize_repo_relative_path(action.path)
        if normalized_path is None:
            return False, None

        if not any(fnmatch(normalized_path, pattern) for pattern in rule["paths"]):
            return False, None

        return True, f"path:{normalized_path}"

    if "domains" in rule:
        if action.domain is None:
            return False, None

        if not any(fnmatch(action.domain, pattern) for pattern in rule["domains"]):
            return False, None

        return True, f"domain:{action.domain}"

    if "commands" in rule:
        if action.command is None:
            return False, None

        if not any(fnmatch(action.command, pattern) for pattern in rule["commands"]):
            return False, None

        return True, f"command:{action.command}"

    if "memory_types" in rule or "scope_kinds" in rule:
        if "memory_types" in rule:
            if action.memory_type is None or not any(
                fnmatch(action.memory_type, pattern) for pattern in rule["memory_types"]
            ):
                return False, None
        if "scope_kinds" in rule:
            if action.scope_kind is None or not any(
                fnmatch(action.scope_kind, pattern) for pattern in rule["scope_kinds"]
            ):
                return False, None
        details = []
        if action.memory_type is not None:
            details.append(f"memory_type:{action.memory_type}")
        if action.scope_kind is not None:
            details.append(f"scope_kind:{action.scope_kind}")
        return True, ",".join(details) if details else None

    return True, None


def evaluate_policy(policy: dict, action: PolicyAction) -> PolicyDecision:
    assert_valid_capability(action.capability)

    for rule in policy["deny"]:
        matched, scope = rule_matches(rule, action)
        if matched:
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                reason=f"Denied by policy `{policy['name']}` for capability `{action.capability}`",
                matched_scope=scope,
            )

    for rule in policy["approval"]:
        matched, scope = rule_matches(rule, action)
        if matched:
            return PolicyDecision(
                allowed=False,
                requires_approval=True,
                reason=f"Approval required by policy `{policy['name']}` for capability `{action.capability}`",
                matched_scope=scope,
            )

    for rule in policy["allow"]:
        matched, scope = rule_matches(rule, action)
        if matched:
            return PolicyDecision(
                allowed=True,
                requires_approval=False,
                reason=f"Allowed by policy `{policy['name']}` for capability `{action.capability}`",
                matched_scope=scope,
            )

    return PolicyDecision(
        allowed=False,
        requires_approval=False,
        reason=f"No allow rule matched in policy `{policy['name']}` for capability `{action.capability}`",
        matched_scope=None,
    )


def enforce_policy(policy: dict, action: PolicyAction) -> PolicyDecision:
    decision = evaluate_policy(policy, action)
    if decision.allowed:
        return decision

    raise PolicyDeniedError(
        decision.reason,
        capability=action.capability,
        policy_name=policy["name"],
    )


def snapshot_policy(policy: dict) -> dict:
    return {
        "name": policy["name"],
        "allow": [dict(rule) for rule in policy["allow"]],
        "approval": [dict(rule) for rule in policy["approval"]],
        "deny": [dict(rule) for rule in policy["deny"]],
    }
