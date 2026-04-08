import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime.policy as policy


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.repo_dir = self.root_dir / "repo"
        self.repo_dir.mkdir()
        self.policies_config = self.root_dir / "policies.yaml"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_policies(self, content: str) -> None:
        self.policies_config.write_text(content.strip() + "\n", encoding="utf-8")

    def test_load_policy_accepts_safe_policy_in_production(self) -> None:
        self.write_policies(
            """
policies:
  safe_readonly:
    allow:
      - capability: model_call
      - capability: exec
        commands:
          - echo
      - capability: file_read
        paths:
          - "**"
    deny:
      - capability: file_write
      - capability: http
"""
        )

        with patch.object(policy, "POLICIES_CONFIG_PATH", self.policies_config), patch.dict(
            policy.os.environ,
            {"CLARITYOS_ENV": "production"},
            clear=True,
        ):
            loaded = policy.load_policy("safe_readonly")

        self.assertEqual(loaded["name"], "safe_readonly")
        self.assertEqual(loaded["allow"][1]["commands"], ["echo"])

    def test_load_policy_rejects_production_exec_wildcard(self) -> None:
        self.write_policies(
            """
policies:
  unsafe_exec:
    allow:
      - capability: exec
        commands:
          - "*"
    deny:
      - capability: file_write
      - capability: http
"""
        )

        with patch.object(policy, "POLICIES_CONFIG_PATH", self.policies_config), patch.dict(
            policy.os.environ,
            {"CLARITYOS_ENV": "production"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "must declare explicit commands in production",
            ):
                policy.load_policy("unsafe_exec")

    def test_load_policy_requires_file_write_and_http_denies_in_production(self) -> None:
        self.write_policies(
            """
policies:
  incomplete:
    allow:
      - capability: model_call
    deny:
      - capability: http
"""
        )

        with patch.object(policy, "POLICIES_CONFIG_PATH", self.policies_config), patch.dict(
            policy.os.environ,
            {"CLARITYOS_ENV": "production"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "must explicitly deny file_write in production",
            ):
                policy.load_policy("incomplete")

    def test_build_agent_policy_blocks_overrides_in_production_by_default(self) -> None:
        self.write_policies(
            """
policies:
  safe_readonly:
    allow:
      - capability: model_call
    deny:
      - capability: file_write
      - capability: http
"""
        )
        agent_config = {
            "policy": "safe_readonly",
            "allow": [{"capability": "exec", "commands": ["echo"]}],
        }

        with patch.object(policy, "POLICIES_CONFIG_PATH", self.policies_config), patch.dict(
            policy.os.environ,
            {"CLARITYOS_ENV": "production"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "Agent policy overrides are disabled in production",
            ):
                policy.build_agent_policy(agent_config)

    def test_build_agent_policy_allows_opted_in_overrides_in_production(self) -> None:
        self.write_policies(
            """
policies:
  safe_readonly:
    allow:
      - capability: model_call
    deny:
      - capability: file_write
      - capability: http
"""
        )
        agent_config = {
            "policy": "safe_readonly",
            "allow": [{"capability": "exec", "commands": ["echo"]}],
        }

        with patch.object(policy, "POLICIES_CONFIG_PATH", self.policies_config), patch.dict(
            policy.os.environ,
            {
                "CLARITYOS_ENV": "production",
                "CLARITYOS_ALLOW_AGENT_POLICY_OVERRIDES": "1",
            },
            clear=True,
        ):
            built = policy.build_agent_policy(agent_config)

        self.assertEqual(built["allow"][-1]["capability"], "exec")


if __name__ == "__main__":
    unittest.main()
