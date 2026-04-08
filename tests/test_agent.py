import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime.artifact as artifact
import runtime.approval as approval
import runtime.agent as agent
import runtime.contracts as contracts
import runtime.memory as memory
import runtime.policy as policy
import runtime.trace as trace
import runtime.tools as tools
import runtime.workflow as workflow


def fake_model(model_name: str, prompt: str) -> dict:
    return {
        "provider": "test",
        "model": "fake-model",
        "output": "ok",
    }


class RunAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.log_dir = self.root_dir / "logs"
        self.approvals_dir = self.root_dir / "approvals"
        self.artifacts_dir = self.root_dir / "artifacts"
        self.memories_dir = self.root_dir / "memories"
        self.workflows_dir = self.root_dir / "workflows"
        self.repo_dir = self.root_dir / "repo"
        self.repo_dir.mkdir()
        self.log_dir.mkdir()
        self.approvals_dir.mkdir()
        self.artifacts_dir.mkdir()
        self.memories_dir.mkdir()
        self.workflows_dir.mkdir()
        self.agents_config = self.root_dir / "agents.yaml"
        self.policies_config = self.root_dir / "policies.yaml"
        self.sample_file = self.repo_dir / "notes.txt"
        self.sample_file.write_text("sample repo file\n", encoding="utf-8")
        self.outside_file = self.root_dir / "outside.txt"
        self.outside_file.write_text("outside repo\n", encoding="utf-8")
        self.agents_config.write_text(
            """
agents:
  default:
    system: "You are a helpful assistant"
    model: fast
    policy: safe_readonly
    budgets:
      max_steps: 4
      max_tool_calls: 2
      max_tokens: 4000
      max_wall_clock_ms: 30000
    tools:
      - echo
      - get_time
      - read_file

  researcher:
    system: "You provide precise, structured answers"
    model: smart
    policy: safe_readonly
    budgets:
      max_steps: 4
      max_tool_calls: 2
      max_tokens: 4000
      max_wall_clock_ms: 30000
    tools:
      - get_time
      - read_file

  memory_tool:
    system: "You manage explicit memory operations"
    model: fast
    policy: memory_basic
    budgets:
      max_steps: 4
      max_tool_calls: 2
      max_tokens: 4000
      max_wall_clock_ms: 30000
    tools:
      - memory_write
      - memory_query

  blocked_memory:
    system: "You can ask for memory tools but policy still denies them"
    model: fast
    policy: safe_readonly
    budgets:
      max_steps: 4
      max_tool_calls: 2
      max_tokens: 4000
      max_wall_clock_ms: 30000
    tools:
      - memory_query

  local:
    system: "You are a helpful assistant"
    model: local_fast
    policy: safe_readonly
    budgets:
      max_steps: 4
      max_tool_calls: 2
      max_tokens: 4000
      max_wall_clock_ms: 30000

  blocked_model:
    system: "You are blocked from model calls"
    model: fast
    policy: no_model
    budgets:
      max_steps: 4
      max_tool_calls: 2
      max_tokens: 4000
      max_wall_clock_ms: 30000
    tools:
      - echo

  tiny_tools:
    system: "You have no tool budget"
    model: fast
    policy: safe_readonly
    budgets:
      max_steps: 4
      max_tool_calls: 0
      max_tokens: 4000
      max_wall_clock_ms: 30000
    tools:
      - echo

  tiny_tokens:
    system: "You have a tiny token budget"
    model: fast
    policy: safe_readonly
    budgets:
      max_steps: 4
      max_tool_calls: 2
      max_tokens: 10
      max_wall_clock_ms: 30000
    tools:
      - echo

  approval_tool:
    system: "You need approval before running echo"
    model: fast
    policy: approval_exec
    budgets:
      max_steps: 4
      max_tool_calls: 2
      max_tokens: 4000
      max_wall_clock_ms: 30000
    tools:
      - echo

  retry_tool:
    system: "You retry transient tool failures once"
    model: fast
    policy: safe_readonly
    budgets:
      max_steps: 4
      max_tool_calls: 2
      max_tokens: 4000
      max_wall_clock_ms: 30000
    retries:
      max_attempts: 1
      backoff_seconds: 0
    tools:
      - echo
""".strip()
            + "\n",
            encoding="utf-8",
        )
        self.policies_config.write_text(
            """
policies:
  safe_readonly:
    allow:
      - capability: model_call
      - capability: exec
        commands:
          - echo
          - get_time
      - capability: file_read
        paths:
          - "**"
    deny:
      - capability: file_write
      - capability: http
      - capability: memory_read
      - capability: memory_write

  no_model:
    allow:
      - capability: exec
        commands:
          - echo
    deny:
      - capability: model_call

  approval_exec:
    approval:
      - capability: exec
        commands:
          - echo
    allow:
      - capability: model_call
      - capability: file_read
        paths:
          - "**"
    deny:
      - capability: file_write
      - capability: http
      - capability: memory_read
      - capability: memory_write

  memory_basic:
    allow:
      - capability: model_call
      - capability: memory_read
        scope_kinds:
          - global
          - agent
          - workflow
          - run
      - capability: memory_write
        memory_types:
          - fact
          - summary
          - observation
          - artifact_ref
        scope_kinds:
          - agent
          - workflow
          - run
    deny:
      - capability: file_write
      - capability: http
""".strip()
            + "\n",
            encoding="utf-8",
        )
        self.trace_patcher = patch.object(trace, "LOG_DIR", self.log_dir)
        self.approval_dir_patcher = patch.object(approval, "APPROVAL_DIR", self.approvals_dir)
        self.artifact_dir_patcher = patch.object(artifact, "ARTIFACT_DIR", self.artifacts_dir)
        self.memory_dir_patcher = patch.object(memory, "MEMORY_DIR", self.memories_dir)
        self.workflow_dir_patcher = patch.object(workflow, "WORKFLOW_DIR", self.workflows_dir)
        self.tools_base_dir_patcher = patch.object(tools, "BASE_DIR", self.repo_dir)
        self.agents_config_patcher = patch.object(agent, "AGENTS_CONFIG_PATH", self.agents_config)
        self.policies_config_patcher = patch.object(
            policy, "POLICIES_CONFIG_PATH", self.policies_config
        )
        self.policy_base_dir_patcher = patch.object(policy, "BASE_DIR", self.repo_dir)
        self.trace_patcher.start()
        self.approval_dir_patcher.start()
        self.artifact_dir_patcher.start()
        self.memory_dir_patcher.start()
        self.workflow_dir_patcher.start()
        self.tools_base_dir_patcher.start()
        self.agents_config_patcher.start()
        self.policies_config_patcher.start()
        self.policy_base_dir_patcher.start()

    def tearDown(self) -> None:
        self.trace_patcher.stop()
        self.approval_dir_patcher.stop()
        self.artifact_dir_patcher.stop()
        self.memory_dir_patcher.stop()
        self.workflow_dir_patcher.stop()
        self.tools_base_dir_patcher.stop()
        self.agents_config_patcher.stop()
        self.policies_config_patcher.stop()
        self.policy_base_dir_patcher.stop()
        self.temp_dir.cleanup()

    def latest_log(self) -> dict:
        log_files = sorted(self.log_dir.glob("run_*.json"))
        self.assertTrue(log_files, "Expected at least one trace log")

        with log_files[-1].open(encoding="utf-8") as file:
            return json.load(file)

    def test_load_agent_respects_env_config_override(self) -> None:
        override_config = self.root_dir / "agents.override.yaml"
        override_config.write_text(
            """
agents:
  override:
    system: "Override agent"
    model: fast
    policy: safe_readonly
    budgets:
      max_steps: 1
      max_tool_calls: 0
      max_tokens: 100
      max_wall_clock_ms: 1000
""".strip()
            + "\n",
            encoding="utf-8",
        )

        with patch.dict(agent.os.environ, {"CLARITYOS_AGENTS_CONFIG": str(override_config)}, clear=True):
            loaded = agent.load_agent("override")

        self.assertEqual(loaded["system"], "Override agent")
        self.assertEqual(loaded["budgets"]["max_steps"], 1)

    @patch.object(agent, "call_model", side_effect=fake_model)
    def test_run_agent_success(self, _mock_call_model) -> None:
        result = agent.run_agent("hello", "default")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["run_type"], "model")
        self.assertEqual(result["agent"], "default")
        self.assertEqual(result["provider"], "test")
        self.assertEqual(result["model"], "fake-model")
        self.assertIsNone(result["tool"])
        self.assertIsNone(result["tool_args"])
        self.assertIsNone(result["tool_output"])
        self.assertIsNone(result["tool_result"])
        self.assertEqual(len(result["artifacts"]), 1)
        saved_artifact = artifact.load_artifact(result["artifacts"][0]["artifact_id"])
        self.assertEqual(saved_artifact["kind"], "model_output")
        self.assertEqual(saved_artifact["value"], "ok")
        self.assertEqual(result["workflow"]["status"], "succeeded")
        self.assertEqual(result["workflow"]["steps"][0]["step_type"], "model")
        saved_workflow = workflow.load_workflow(result["workflow"]["workflow_id"])
        self.assertEqual(saved_workflow.status, "succeeded")
        self.assertEqual(saved_workflow.artifacts[0]["artifact_id"], result["artifacts"][0]["artifact_id"])
        self.assertEqual(result["output"], "ok")

    @patch.object(agent, "call_model", side_effect=fake_model)
    def test_trace_created_for_success(self, _mock_call_model) -> None:
        result = agent.run_agent("hello", "default", job_id="job-123", worker_id="worker-123")

        payload = self.latest_log()

        self.assertEqual(payload["run_type"], "model")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["version"], "v0.8")
        self.assertEqual(payload["schema"], "trace.v2")
        self.assertEqual(payload["agent"], "default")
        self.assertEqual(payload["workflow"]["status"], "succeeded")
        self.assertEqual(payload["workflow"]["current_step_id"], "finish_step")
        self.assertEqual(payload["policy_snapshot"]["name"], "safe_readonly")
        self.assertEqual(payload["context"]["input"], "hello")
        self.assertEqual(payload["context"]["model_alias"], "fast")
        self.assertEqual(payload["result"]["model"]["provider"], "test")
        self.assertEqual(payload["result"]["model"]["model"], "fake-model")
        self.assertEqual(payload["result"]["output"], "ok")
        self.assertEqual(payload["budget"]["limits"]["max_steps"], 4)
        self.assertEqual(payload["budget"]["used"]["steps_used"], 1)
        self.assertEqual(payload["decision_log"][0]["stage"], "model_policy_check")
        self.assertTrue(payload["decision_log"][0]["allowed"])
        self.assertEqual(payload["source_attribution"]["input"][0]["type"], "user_input")
        self.assertEqual(payload["source_attribution"]["context"][0]["type"], "system_prompt")
        self.assertEqual(payload["source_attribution"]["context"][1]["type"], "composed_prompt")
        self.assertEqual(payload["source_attribution"]["output"]["type"], "model")
        self.assertGreater(payload["cost_accounting"]["estimated_tokens"]["total"], 0)
        self.assertEqual(payload["cost_accounting"]["operations"]["model_calls"], 1)
        self.assertEqual(payload["correlation_ids"]["run_ids"], [payload["run_id"]])
        self.assertEqual(payload["correlation_ids"]["workflow_ids"], [result["workflow"]["workflow_id"]])
        self.assertEqual(payload["correlation_ids"]["job_ids"], ["job-123"])
        self.assertEqual(payload["correlation_ids"]["worker_ids"], ["worker-123"])
        self.assertEqual(payload["correlation_ids"]["artifact_ids"], [result["artifacts"][0]["artifact_id"]])
        self.assertEqual(payload["correlation_ids"]["memory_ids"], [])
        self.assertEqual(payload["correlation_ids"]["shared_memory_ids"], [])
        self.assertEqual(payload["correlation_ids"]["child_workflow_ids"], [])
        self.assertEqual(payload["correlation_ids"]["delegation"], {})
        self.assertIn("run_id", payload)
        self.assertIn("duration_ms", payload)
        self.assertIn("timestamp", payload)

    @patch.object(agent, "call_model", side_effect=fake_model)
    def test_run_agent_shared_memory_handoff_is_added_to_prompt_and_trace(self, _mock_call_model) -> None:
        result = agent.run_agent(
            "Summarize the parent result",
            "researcher",
            parent_run_id="run-parent",
            parent_workflow_id="wf-parent",
            root_workflow_id="wf-parent",
            workflow_depth=1,
            delegation={
                "role": "summarizer",
                "assigned_by_workflow_id": "wf-parent",
                "assigned_by_run_id": "run-parent",
                "allowed_capabilities": ["model_call"],
                "allowed_tools": [],
            },
            shared_memories=[
                {
                    "memory_id": "memory-123",
                    "memory_type": "fact",
                    "scope": {"kind": "workflow", "value": "wf-parent"},
                    "workflow_id": "wf-parent",
                    "payload_summary": "Retries are bounded",
                }
            ],
        )

        self.assertEqual(result["workflow"]["delegation"]["role"], "summarizer")
        self.assertEqual(result["workflow"]["shared_memories"][0]["memory_id"], "memory-123")
        self.assertIn("SHARED MEMORY:", result["prompt"])
        self.assertIn("Retries are bounded", result["prompt"])

        payload = self.latest_log()

        self.assertEqual(payload["decision_log"][0]["stage"], "delegation_check")
        self.assertEqual(payload["source_attribution"]["context"][0]["type"], "shared_memory")
        self.assertEqual(payload["source_attribution"]["context"][0]["memory_id"], "memory-123")
        self.assertEqual(payload["correlation_ids"]["run_ids"], [payload["run_id"], "run-parent"])
        self.assertEqual(
            payload["correlation_ids"]["workflow_ids"],
            [result["workflow"]["workflow_id"], "wf-parent"],
        )
        self.assertEqual(payload["correlation_ids"]["shared_memory_ids"], ["memory-123"])
        self.assertEqual(
            payload["correlation_ids"]["delegation"],
            {
                "assigned_by_workflow_id": "wf-parent",
                "assigned_by_run_id": "run-parent",
            },
        )

    def test_run_agent_tool_success(self) -> None:
        result = agent.run_agent(
            "hello",
            "default",
            tool_name="echo",
            tool_args={"text": "tool says hi"},
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["run_type"], "tool")
        self.assertEqual(result["agent"], "default")
        self.assertIsNone(result["prompt"])
        self.assertIsNone(result["provider"])
        self.assertIsNone(result["model"])
        self.assertEqual(result["tool"], "echo")
        self.assertEqual(result["tool_args"], {"text": "tool says hi"})
        self.assertEqual(result["tool_output"], "tool says hi")
        self.assertTrue(result["tool_result"]["ok"])
        self.assertEqual(len(result["artifacts"]), 1)
        saved_artifact = artifact.load_artifact(result["artifacts"][0]["artifact_id"])
        self.assertEqual(saved_artifact["kind"], "tool_output")
        self.assertEqual(saved_artifact["value"], "tool says hi")
        self.assertEqual(result["workflow"]["status"], "succeeded")
        self.assertEqual(result["workflow"]["steps"][0]["step_type"], "tool")
        self.assertEqual(result["tool_result"]["output"]["value"], "tool says hi")
        self.assertEqual(result["output"], "tool says hi")

        payload = self.latest_log()

        self.assertEqual(payload["run_type"], "tool")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["agent"], "default")
        self.assertEqual(payload["workflow"]["status"], "succeeded")
        self.assertEqual(payload["policy_snapshot"]["name"], "safe_readonly")
        self.assertEqual(payload["result"]["tool"]["name"], "echo")
        self.assertEqual(payload["result"]["tool"]["input"]["args"], {"text": "tool says hi"})
        self.assertEqual(payload["result"]["tool"]["output"]["value"], "tool says hi")
        self.assertEqual(payload["result"]["output"], "tool says hi")
        self.assertEqual(payload["budget"]["used"]["steps_used"], 1)
        self.assertEqual(payload["budget"]["used"]["tool_calls_used"], 1)
        self.assertEqual(payload["decision_log"][0]["stage"], "tool_policy_check")
        self.assertTrue(payload["decision_log"][0]["allowed"])
        self.assertEqual(payload["source_attribution"]["input"][1]["type"], "tool_args")
        self.assertEqual(payload["source_attribution"]["output"]["type"], "tool")
        self.assertEqual(payload["cost_accounting"]["operations"]["tool_calls"], 1)

    def test_run_agent_delegation_denies_disallowed_tool(self) -> None:
        with self.assertRaisesRegex(PermissionError, "does not allow tool `echo`"):
            agent.run_agent(
                "",
                "default",
                tool_name="echo",
                tool_args={"text": "hello"},
                parent_run_id="run-parent",
                parent_workflow_id="wf-parent",
                root_workflow_id="wf-parent",
                workflow_depth=1,
                delegation={
                    "role": "reader",
                    "assigned_by_workflow_id": "wf-parent",
                    "assigned_by_run_id": "run-parent",
                    "allowed_capabilities": ["exec"],
                    "allowed_tools": ["get_time"],
                },
            )

    def test_run_agent_get_time_tool_success(self) -> None:
        result = agent.run_agent(
            "",
            "default",
            tool_name="get_time",
            tool_args={},
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["run_type"], "tool")
        self.assertEqual(result["tool"], "get_time")
        self.assertIn("utc", result["tool_output"])
        self.assertTrue(result["tool_output"]["utc"].endswith("+00:00"))

        payload = self.latest_log()

        self.assertEqual(payload["run_type"], "tool")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["result"]["tool"]["name"], "get_time")
        self.assertEqual(payload["result"]["tool"]["input"]["args"], {})
        self.assertIn("utc", payload["result"]["tool"]["output"]["value"])
        self.assertTrue(payload["result"]["tool"]["ok"])

    def test_run_agent_read_file_tool_success(self) -> None:
        result = agent.run_agent(
            "",
            "default",
            tool_name="read_file",
            tool_args={"path": "notes.txt"},
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["run_type"], "tool")
        self.assertEqual(result["tool"], "read_file")
        self.assertEqual(result["tool_args"], {"path": "notes.txt"})
        self.assertEqual(result["tool_output"], "sample repo file\n")

        payload = self.latest_log()

        self.assertEqual(payload["run_type"], "tool")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["result"]["tool"]["name"], "read_file")
        self.assertEqual(payload["result"]["tool"]["input"]["args"], {"path": "notes.txt"})
        self.assertEqual(payload["result"]["tool"]["output"]["value"], "sample repo file\n")
        self.assertTrue(payload["result"]["tool"]["ok"])

    def test_run_agent_memory_write_tool_success(self) -> None:
        result = agent.run_agent(
            "",
            "memory_tool",
            tool_name="memory_write",
            tool_args={
                "memory_type": "fact",
                "scope_kind": "agent",
                "agent": "researcher",
                "payload": {"statement": "Retries are bounded", "subject": "retry"},
                "tags": ["runtime", "retry"],
            },
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["run_type"], "tool")
        self.assertEqual(result["tool"], "memory_write")
        self.assertEqual(result["tool_output"]["memory_type"], "fact")
        self.assertEqual(result["tool_output"]["scope"], {"kind": "agent", "value": "researcher"})
        saved_memory = memory.load_memory(result["tool_output"]["memory_id"])
        self.assertEqual(saved_memory["payload"]["statement"], "Retries are bounded")
        self.assertEqual(saved_memory["tags"], ["runtime", "retry"])
        self.assertEqual(saved_memory["agent"], "researcher")
        self.assertEqual(saved_memory["workflow_id"], result["workflow"]["workflow_id"])
        self.assertEqual(saved_memory["run_id"], result["workflow"]["latest_run_id"])
        self.assertEqual(result["workflow"]["memories"][0]["memory_id"], saved_memory["memory_id"])

        payload = self.latest_log()

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["result"]["tool"]["name"], "memory_write")
        self.assertEqual(payload["result"]["tool"]["input"]["args"]["memory_type"], "fact")
        self.assertEqual(payload["result"]["tool"]["output"]["value"]["memory_type"], "fact")

    def test_run_agent_memory_query_tool_success(self) -> None:
        memory.create_memory(
            memory_type="summary",
            scope_kind="agent",
            agent="researcher",
            payload={"text": "Retry backoff prevents hot looping"},
            tags=["retry"],
        )
        memory.create_memory(
            memory_type="fact",
            scope_kind="agent",
            agent="researcher",
            payload={"statement": "Queue processing is durable", "subject": "queue"},
            tags=["queue"],
        )

        result = agent.run_agent(
            "",
            "memory_tool",
            tool_name="memory_query",
            tool_args={
                "query": "retry",
                "scope_kind": "agent",
                "agent": "researcher",
                "limit": 2,
                "max_chars": 200,
            },
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["tool"], "memory_query")
        self.assertEqual(result["tool_output"]["query"], "retry")
        self.assertEqual(result["tool_output"]["result_count"], 1)
        self.assertEqual(result["tool_output"]["results"][0]["memory_type"], "summary")
        self.assertIn("retry", result["tool_output"]["results"][0]["matched_terms"])

        payload = self.latest_log()

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["result"]["tool"]["name"], "memory_query")
        self.assertEqual(payload["result"]["tool"]["output"]["value"]["query"], "retry")

    def test_run_agent_memory_query_denied_by_policy(self) -> None:
        with self.assertRaisesRegex(
            PermissionError, "Denied by policy `safe_readonly` for capability `memory_read`"
        ):
            agent.run_agent(
                "",
                "blocked_memory",
                tool_name="memory_query",
                tool_args={"query": "retry", "scope_kind": "agent"},
            )

        payload = self.latest_log()

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["result"]["tool"]["name"], "memory_query")
        self.assertEqual(payload["result"]["tool"]["error"]["error_type"], "PolicyDeniedError")
        self.assertFalse(payload["decision_log"][0]["allowed"])

    def test_run_agent_memory_write_global_scope_denied_by_policy(self) -> None:
        with self.assertRaisesRegex(
            PermissionError, "No allow rule matched in policy `memory_basic` for capability `memory_write`"
        ):
            agent.run_agent(
                "",
                "memory_tool",
                tool_name="memory_write",
                tool_args={
                    "memory_type": "fact",
                    "scope_kind": "global",
                    "payload": {"statement": "global memory is restricted"},
                },
            )

        payload = self.latest_log()

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["result"]["tool"]["name"], "memory_write")
        self.assertEqual(payload["result"]["tool"]["error"]["error_type"], "PolicyDeniedError")
        self.assertFalse(payload["decision_log"][0]["allowed"])

    def test_run_agent_disallowed_tool_logs_error(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "Tool not allowed for agent `researcher`: echo"
        ):
            agent.run_agent(
                "hello",
                "researcher",
                tool_name="echo",
                tool_args={"text": "blocked"},
            )

        payload = self.latest_log()

        self.assertEqual(payload["run_type"], "tool")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["agent"], "researcher")
        self.assertEqual(payload["workflow"]["status"], "failed")
        self.assertEqual(payload["context"]["input"], "hello")
        self.assertEqual(payload["result"]["tool"]["name"], "echo")
        self.assertEqual(payload["result"]["tool"]["input"]["args"], {"text": "blocked"})
        self.assertIsNone(payload["result"]["tool"]["output"])
        self.assertFalse(payload["result"]["tool"]["ok"])
        self.assertEqual(payload["result"]["error"]["error_type"], "ValueError")
        self.assertIn("Tool not allowed for agent `researcher`: echo", payload["result"]["error"]["message"])

    @patch.object(agent, "call_tool", side_effect=RuntimeError("tool exploded"))
    def test_run_agent_tool_failure_logs_error(self, _mock_call_tool) -> None:
        with self.assertRaisesRegex(RuntimeError, "tool exploded"):
            agent.run_agent(
                "hello",
                "default",
                tool_name="echo",
                tool_args={"text": "boom"},
            )

        payload = self.latest_log()

        self.assertEqual(payload["run_type"], "tool")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["agent"], "default")
        self.assertEqual(payload["workflow"]["status"], "failed")
        self.assertEqual(payload["result"]["tool"]["name"], "echo")
        self.assertEqual(payload["result"]["tool"]["input"]["args"], {"text": "boom"})
        self.assertIsNone(payload["result"]["tool"]["output"])
        self.assertFalse(payload["result"]["tool"]["ok"])
        self.assertEqual(payload["result"]["tool"]["error"]["error_type"], "RuntimeError")
        self.assertEqual(payload["result"]["error"]["message"], "tool exploded")

    def test_run_agent_read_file_blocks_path_traversal(self) -> None:
        with self.assertRaisesRegex(
            PermissionError, "No allow rule matched in policy `safe_readonly` for capability `file_read`"
        ):
            agent.run_agent(
                "",
                "default",
                tool_name="read_file",
                tool_args={"path": "../outside.txt"},
            )

        payload = self.latest_log()

        self.assertEqual(payload["run_type"], "tool")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["workflow"]["status"], "failed")
        self.assertEqual(payload["result"]["tool"]["name"], "read_file")
        self.assertEqual(payload["result"]["tool"]["input"]["args"], {"path": "../outside.txt"})
        self.assertIsNone(payload["result"]["tool"]["output"])
        self.assertFalse(payload["result"]["tool"]["ok"])
        self.assertEqual(payload["result"]["tool"]["error"]["error_type"], "PolicyDeniedError")
        self.assertIn("No allow rule matched in policy `safe_readonly`", payload["result"]["tool"]["error"]["message"])
        self.assertFalse(payload["decision_log"][0]["allowed"])

    def test_run_agent_read_file_missing_logs_error(self) -> None:
        with self.assertRaisesRegex(FileNotFoundError, "File not found: missing.txt"):
            agent.run_agent(
                "",
                "default",
                tool_name="read_file",
                tool_args={"path": "missing.txt"},
            )

        payload = self.latest_log()

        self.assertEqual(payload["run_type"], "tool")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["workflow"]["status"], "failed")
        self.assertEqual(payload["result"]["tool"]["name"], "read_file")
        self.assertEqual(payload["result"]["tool"]["input"]["args"], {"path": "missing.txt"})
        self.assertIsNone(payload["result"]["tool"]["output"])
        self.assertFalse(payload["result"]["tool"]["ok"])
        self.assertEqual(payload["result"]["tool"]["error"]["failure_type"], "not_found")
        self.assertEqual(payload["result"]["tool"]["error"]["message"], "File not found: missing.txt")

    def test_run_agent_missing_logs_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown agent: missing"):
            agent.run_agent("hello", "missing")

        payload = self.latest_log()

        self.assertEqual(payload["run_type"], "model")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["version"], "v0.8")
        self.assertEqual(payload["workflow"]["status"], "failed")
        self.assertEqual(payload["context"]["input"], "hello")
        self.assertEqual(payload["agent"], "missing")
        self.assertIsNone(payload["context"]["prompt"])
        self.assertIsNone(payload["context"]["model_alias"])
        self.assertEqual(payload["result"]["error"]["error_type"], "ValueError")
        self.assertIn("Unknown agent: missing", payload["result"]["error"]["message"])
        self.assertIn("run_id", payload)
        self.assertIn("duration_ms", payload)
        self.assertIn("timestamp", payload)

    def test_run_agent_model_policy_denied_logs_error(self) -> None:
        with self.assertRaisesRegex(
            PermissionError, "Denied by policy `no_model` for capability `model_call`"
        ):
            agent.run_agent("hello", "blocked_model")

        payload = self.latest_log()

        self.assertEqual(payload["run_type"], "model")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["agent"], "blocked_model")
        self.assertEqual(payload["workflow"]["status"], "failed")
        self.assertEqual(payload["policy_snapshot"]["name"], "no_model")
        self.assertEqual(payload["result"]["error"]["error_type"], "PolicyDeniedError")
        self.assertIn("Denied by policy `no_model`", payload["result"]["error"]["message"])
        self.assertFalse(payload["decision_log"][0]["allowed"])

    def test_run_agent_tool_budget_exhaustion_logs_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Run exceeded `max_tool_calls` budget"):
            agent.run_agent(
                "",
                "tiny_tools",
                tool_name="echo",
                tool_args={"text": "blocked by budget"},
            )

        payload = self.latest_log()

        self.assertEqual(payload["run_type"], "tool")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["agent"], "tiny_tools")
        self.assertEqual(payload["workflow"]["status"], "failed")
        self.assertEqual(payload["result"]["error"]["error_type"], "BudgetExceededError")
        self.assertEqual(payload["budget"]["used"]["tool_calls_used"], 0)

    @patch.object(agent, "call_model", side_effect=fake_model)
    def test_run_agent_token_budget_exhaustion_logs_error(self, _mock_call_model) -> None:
        with self.assertRaisesRegex(RuntimeError, "Run exceeded `max_tokens` budget"):
            agent.run_agent("this input is much too long for the tiny budget", "tiny_tokens")

        payload = self.latest_log()

        self.assertEqual(payload["run_type"], "model")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["agent"], "tiny_tokens")
        self.assertEqual(payload["workflow"]["status"], "failed")
        self.assertEqual(payload["result"]["error"]["error_type"], "BudgetExceededError")
        self.assertEqual(payload["budget"]["used"]["steps_used"], 1)

    def test_run_agent_tool_requests_approval(self) -> None:
        result = agent.run_agent(
            "",
            "approval_tool",
            tool_name="echo",
            tool_args={"text": "needs approval"},
        )

        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["run_type"], "tool")
        self.assertEqual(result["tool"], "echo")
        self.assertIsNone(result["tool_output"])
        self.assertIsNone(result["tool_result"])
        self.assertEqual(result["approval"]["status"], "pending")
        self.assertEqual(result["workflow"]["status"], "waiting")
        self.assertEqual(result["approval"]["workflow_id"], result["workflow"]["workflow_id"])

        approval_record = approval.get_approval(result["approval"]["approval_id"])
        self.assertEqual(approval_record["status"], "pending")
        self.assertEqual(approval_record["request"]["tool_args"], {"text": "needs approval"})
        self.assertEqual(approval_record["workflow_id"], result["workflow"]["workflow_id"])
        saved_workflow = workflow.load_workflow(result["workflow"]["workflow_id"])
        self.assertEqual(saved_workflow.status, "waiting")
        self.assertEqual(saved_workflow.current_step_id, f"approval_wait:{result['approval']['approval_id']}")

        payload = self.latest_log()

        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["workflow"]["status"], "waiting")
        self.assertEqual(payload["result"]["approval"]["status"], "pending")
        self.assertEqual(payload["source_attribution"]["output"]["type"], "approval")
        self.assertTrue(payload["decision_log"][0]["requires_approval"])
        self.assertEqual(payload["decision_log"][1]["stage"], "approval_requested")
        self.assertEqual(payload["decision_log"][2]["stage"], "approval_pending")
        self.assertEqual(payload["cost_accounting"]["operations"]["approvals_requested"], 1)

    @patch.object(
        agent,
        "call_tool",
        return_value=contracts.build_tool_failure(
            name="echo",
            args={"text": "retry me"},
            exc=TimeoutError("transient timeout"),
        ),
    )
    def test_run_agent_retryable_tool_failure_waits_for_retry(self, _mock_call_tool) -> None:
        result = agent.run_agent(
            "",
            "retry_tool",
            tool_name="echo",
            tool_args={"text": "retry me"},
        )

        self.assertEqual(result["status"], "retry_wait")
        self.assertEqual(result["workflow"]["status"], "waiting")
        self.assertEqual(result["workflow"]["current_step_id"], "retry_wait:1")
        self.assertEqual(result["retry"]["attempts_used"], 1)
        self.assertEqual(result["retry"]["retries_remaining"], 0)
        self.assertEqual(result["tool_result"]["error"]["retryable"], True)

        saved_workflow = workflow.load_workflow(result["workflow"]["workflow_id"])
        self.assertEqual(saved_workflow.status, "waiting")
        self.assertEqual(saved_workflow.retry_state["attempts_used"], 1)
        self.assertEqual(saved_workflow.current_step_id, "retry_wait:1")

        payload = self.latest_log()

        self.assertEqual(payload["status"], "retry_wait")
        self.assertEqual(payload["workflow"]["status"], "waiting")
        self.assertEqual(payload["decision_log"][-1]["stage"], "retry_scheduled")
        self.assertEqual(payload["result"]["retry"]["attempts_used"], 1)

    def test_run_agent_tool_resumes_after_approval(self) -> None:
        pending_result = agent.run_agent(
            "",
            "approval_tool",
            tool_name="echo",
            tool_args={"text": "needs approval"},
        )
        approval_id = pending_result["approval"]["approval_id"]

        approved = approval.approve_approval(approval_id)
        self.assertEqual(approved["status"], "approved")

        result = agent.run_agent(
            "",
            "approval_tool",
            tool_name="echo",
            tool_args={"text": "needs approval"},
            approval_id=approval_id,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["tool_output"], "needs approval")
        self.assertEqual(result["approval"]["status"], "resumed")
        self.assertEqual(result["workflow"]["status"], "succeeded")
        self.assertEqual(result["workflow"]["current_step_id"], "finish_step")
        saved_workflow = workflow.load_workflow(result["workflow"]["workflow_id"])
        self.assertEqual(saved_workflow.status, "succeeded")
        self.assertEqual(saved_workflow.latest_run_id, result["workflow"]["latest_run_id"])

        payload = self.latest_log()

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["workflow"]["status"], "succeeded")
        self.assertEqual(payload["parent_run_id"], pending_result["approval"]["requested_run_id"])
        self.assertEqual(payload["result"]["tool"]["output"]["value"], "needs approval")
        self.assertEqual(payload["decision_log"][0]["stage"], "approval_resumed")
        self.assertEqual(payload["decision_log"][1]["stage"], "tool_policy_check")
        self.assertEqual(payload["cost_accounting"]["operations"]["approvals_resumed"], 1)

    def test_run_agent_denied_approval_blocks_resume(self) -> None:
        pending_result = agent.run_agent(
            "",
            "approval_tool",
            tool_name="echo",
            tool_args={"text": "needs approval"},
        )
        approval_id = pending_result["approval"]["approval_id"]

        denied = approval.deny_approval(approval_id)
        self.assertEqual(denied["status"], "denied")

        with self.assertRaisesRegex(PermissionError, f"Approval `{approval_id}` was denied"):
            agent.run_agent(
                "",
                "approval_tool",
                tool_name="echo",
                tool_args={"text": "needs approval"},
                approval_id=approval_id,
            )

    def test_call_tool_returns_failure_envelope(self) -> None:
        result = tools.call_tool("read_file", {"path": "missing.txt"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["name"], "read_file")
        self.assertEqual(result["input"]["args"], {"path": "missing.txt"})
        self.assertIsNone(result["output"])
        self.assertEqual(result["error"]["failure_type"], "not_found")
        self.assertEqual(result["error"]["error_type"], "FileNotFoundError")

    def test_exception_from_tool_result_maps_failure_types(self) -> None:
        result = contracts.build_tool_failure(
            name="read_file",
            args={"path": "missing.txt"},
            exc=FileNotFoundError("File not found: missing.txt"),
        )

        exc = contracts.exception_from_tool_result(result)

        self.assertIsInstance(exc, FileNotFoundError)
        self.assertEqual(str(exc), "File not found: missing.txt")


if __name__ == "__main__":
    unittest.main()
