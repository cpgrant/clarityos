from dataclasses import dataclass
from fnmatch import fnmatch
import os
from pathlib import Path

import yaml

from runtime.errors import PolicyDeniedError


BASE_DIR = Path(__file__).resolve().parent.parent
POLICIES_CONFIG_PATH = BASE_DIR / "config" / "policies.yaml"
POLICIES_CONFIG_ENV_VAR = "CLARITYCLAW_POLICIES_CONFIG"
LEGACY_POLICIES_CONFIG_ENV_VAR = "CLARITYOS_POLICIES_CONFIG"
PRODUCTION_ENV_VAR = "CLARITYCLAW_ENV"
LEGACY_PRODUCTION_ENV_VAR = "CLARITYOS_ENV"
ALLOW_POLICY_OVERRIDES_ENV_VAR = "CLARITYCLAW_ALLOW_AGENT_POLICY_OVERRIDES"
LEGACY_ALLOW_POLICY_OVERRIDES_ENV_VAR = "CLARITYOS_ALLOW_AGENT_POLICY_OVERRIDES"
CAPABILITY_CLASSES = {
    "model_call",
    "file_read",
    "file_write",
    "http",
    "exec",
    "runtime_read",
    "runtime_write",
    "memory_read",
    "memory_write",
}
PRODUCTION_ENV_NAMES = {"production", "prod"}
REQUIRED_PRODUCTION_DENIES = {"file_write", "http"}
BROAD_MATCH_PATTERNS = {"*", "**"}


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


def runtime_environment() -> str:
    value = os.getenv(PRODUCTION_ENV_VAR)
    if value is None:
        value = os.getenv(LEGACY_PRODUCTION_ENV_VAR, "development")
    if not isinstance(value, str) or not value.strip():
        return "development"
    return value.strip().lower()


def production_mode_enabled() -> bool:
    return runtime_environment() in PRODUCTION_ENV_NAMES


def env_flag_enabled(*names: str) -> bool:
    for name in names:
        value = os.getenv(name)
        if not isinstance(value, str):
            continue
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def allow_agent_policy_overrides() -> bool:
    return env_flag_enabled(ALLOW_POLICY_OVERRIDES_ENV_VAR, LEGACY_ALLOW_POLICY_OVERRIDES_ENV_VAR)


def policies_config_path() -> Path:
    for name in (POLICIES_CONFIG_ENV_VAR, LEGACY_POLICIES_CONFIG_ENV_VAR):
        configured = os.getenv(name)
        if isinstance(configured, str) and configured.strip():
            return Path(configured.strip())
    return POLICIES_CONFIG_PATH


def normalize_rule_list(value: object, *, field_name: str) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Policy `{field_name}` must be a list")

    normalized = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError(f"Policy `{field_name}` entries must be objects")
        normalized.append(dict(entry))
    return normalized


def rule_contains_broad_pattern(values: object) -> bool:
    if not isinstance(values, list):
        return True
    for item in values:
        if not isinstance(item, str) or not item.strip():
            return True
        if item.strip() in BROAD_MATCH_PATTERNS:
            return True
    return False


def validate_rule(rule: dict, *, policy_name: str, list_name: str) -> dict:
    capability = rule.get("capability")
    if not isinstance(capability, str) or not capability.strip():
        raise ValueError(f"Policy `{policy_name}` {list_name} rules require a non-empty `capability`")
    capability = capability.strip()
    assert_valid_capability(capability)

    normalized = dict(rule)
    normalized["capability"] = capability

    if production_mode_enabled() and list_name != "deny":
        if capability == "exec" and rule_contains_broad_pattern(normalized.get("commands")):
            raise ValueError(
                f"Policy `{policy_name}` {list_name} rule for `exec` must declare explicit commands in production"
            )
        if capability == "http" and rule_contains_broad_pattern(normalized.get("domains")):
            raise ValueError(
                f"Policy `{policy_name}` {list_name} rule for `http` must declare explicit domains in production"
            )
        if capability == "file_write" and rule_contains_broad_pattern(normalized.get("paths")):
            raise ValueError(
                f"Policy `{policy_name}` {list_name} rule for `file_write` must declare explicit paths in production"
            )

    return normalized


def validate_policy_rules(policy_name: str, policy: dict) -> dict:
    normalized = {
        "name": policy_name,
        "allow": [
            validate_rule(rule, policy_name=policy_name, list_name="allow")
            for rule in normalize_rule_list(policy.get("allow"), field_name=f"{policy_name}.allow")
        ],
        "approval": [
            validate_rule(rule, policy_name=policy_name, list_name="approval")
            for rule in normalize_rule_list(policy.get("approval"), field_name=f"{policy_name}.approval")
        ],
        "deny": [
            validate_rule(rule, policy_name=policy_name, list_name="deny")
            for rule in normalize_rule_list(policy.get("deny"), field_name=f"{policy_name}.deny")
        ],
    }

    if production_mode_enabled():
        denied_capabilities = {rule["capability"] for rule in normalized["deny"]}
        missing_denies = sorted(REQUIRED_PRODUCTION_DENIES - denied_capabilities)
        if missing_denies:
            raise ValueError(
                f"Policy `{policy_name}` must explicitly deny {', '.join(missing_denies)} in production"
            )

    return normalized


def load_policies() -> dict:
    with policies_config_path().open() as file:
        data = yaml.safe_load(file) or {}

    return data.get("policies", {})


def load_policy(name: str) -> dict:
    policies = load_policies()
    if name not in policies:
        raise ValueError(f"Unknown policy: {name}")

    policy = policies[name] or {}
    return validate_policy_rules(name, policy)


def build_agent_policy(agent_config: dict) -> dict:
    policy_name = agent_config.get("policy")
    if not isinstance(policy_name, str) or not policy_name.strip():
        raise ValueError("Agent is missing required `policy`")

    policy = load_policy(policy_name)
    agent_allow = normalize_rule_list(agent_config.get("allow"), field_name="agent.allow")
    agent_approval = normalize_rule_list(agent_config.get("approval"), field_name="agent.approval")
    agent_deny = normalize_rule_list(agent_config.get("deny"), field_name="agent.deny")
    if production_mode_enabled() and not allow_agent_policy_overrides():
        if agent_allow or agent_approval or agent_deny:
            raise ValueError(
                "Agent policy overrides are disabled in production; "
                f"set `{ALLOW_POLICY_OVERRIDES_ENV_VAR}=1` to allow them explicitly"
            )
    agent_allow = [
        validate_rule(rule, policy_name=policy["name"], list_name="agent.allow")
        for rule in agent_allow
    ]
    agent_approval = [
        validate_rule(rule, policy_name=policy["name"], list_name="agent.approval")
        for rule in agent_approval
    ]
    agent_deny = [
        validate_rule(rule, policy_name=policy["name"], list_name="agent.deny")
        for rule in agent_deny
    ]

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
        "runtime_environment": runtime_environment(),
        "production_mode": production_mode_enabled(),
        "agent_policy_overrides_allowed": allow_agent_policy_overrides(),
    }
