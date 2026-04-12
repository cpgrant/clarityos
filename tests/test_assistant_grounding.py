import unittest
from unittest.mock import patch

from runtime.assistant_grounding import build_assistant_prompt_context, extract_query_terms


class AssistantGroundingTests(unittest.TestCase):
    def test_extract_query_terms_prefers_project_keywords(self) -> None:
        terms = extract_query_terms("How close is ClarityClaw to an OpenClaw-like system?")

        self.assertIn("clarityclaw", terms)
        self.assertIn("openclaw", terms)

    @patch("runtime.assistant_grounding.guarded_tool_call")
    def test_build_assistant_prompt_context_adds_tool_guided_excerpts(self, mock_guarded_tool_call) -> None:
        def fake_tool_call(agent_name: str, name: str, args: dict | None = None) -> dict | None:
            self.assertEqual(agent_name, "researcher")
            if name == "search_files":
                return {
                    "ok": True,
                    "output": {
                        "value": {
                            "hits": [
                                {
                                    "path": "docs/roadmap.md",
                                    "line_number": 12,
                                    "line": "Current focus: v1.3",
                                    "match_preview": "Current focus: v1.3",
                                }
                            ]
                        }
                    },
                }
            if name == "read_file_range":
                return {
                    "ok": True,
                    "output": {
                        "value": {
                            "path": "docs/roadmap.md",
                            "start_line": 11,
                            "end_line": 14,
                            "content": "Current focus: v1.3\nNext planned step: slice 2",
                        }
                    },
                }
            if name == "fetch_url":
                return None
            raise AssertionError(f"Unexpected tool: {name}")

        mock_guarded_tool_call.side_effect = fake_tool_call

        context = build_assistant_prompt_context(
            surface="assistant_web",
            user_input="How close is ClarityClaw to an OpenClaw-like system?",
            agent_name="researcher",
        )

        sources = [entry["source"] for entry in context]
        self.assertIn("README.md", sources)
        self.assertIn("docs/roadmap.md", sources)
        self.assertTrue(any(source.startswith("docs/roadmap.md:") for source in sources))
        self.assertIn("grounding_summary", sources)
        self.assertIn("answer_structure", sources)

    @patch("runtime.assistant_grounding.guarded_tool_call")
    def test_build_assistant_prompt_context_adds_runtime_inspection_when_ids_present(self, mock_guarded_tool_call) -> None:
        def fake_tool_call(agent_name: str, name: str, args: dict | None = None) -> dict | None:
            self.assertEqual(agent_name, "researcher")
            if name == "inspect_workflow":
                return {
                    "ok": True,
                    "output": {
                        "value": {
                            "workflow": {"status": "succeeded", "agent": "researcher", "run_type": "model"},
                            "current_step": {"step_type": "finish", "status": "completed"},
                            "failure": None,
                            "incident": {"rollup": {"current_blocker": None}},
                        }
                    },
                }
            if name == "search_files":
                return {"ok": True, "output": {"value": {"hits": []}}}
            if name == "fetch_url":
                return None
            raise AssertionError(f"Unexpected tool: {name}")

        mock_guarded_tool_call.side_effect = fake_tool_call

        workflow_id = "123e4567-e89b-12d3-a456-426614174000"
        context = build_assistant_prompt_context(
            surface="assistant_web",
            user_input=f"What is the status of workflow {workflow_id}?",
            agent_name="researcher",
        )

        self.assertTrue(any(entry["source"] == f"inspect_workflow:{workflow_id}" for entry in context))

    @patch("runtime.assistant_grounding.guarded_tool_call")
    def test_build_assistant_prompt_context_adds_external_fetch_excerpt(self, mock_guarded_tool_call) -> None:
        def fake_tool_call(agent_name: str, name: str, args: dict | None = None) -> dict | None:
            self.assertEqual(agent_name, "researcher")
            if name == "fetch_url":
                return {
                    "ok": True,
                    "output": {
                        "value": {
                            "url": "https://docs.openclaw.ai/",
                            "content": "OpenClaw is a self-hosted AI gateway with many channels.",
                            "summary": "OpenClaw docs: self-hosted AI gateway with many channels.",
                        }
                    },
                }
            if name == "search_files":
                return {"ok": True, "output": {"value": {"hits": []}}}
            raise AssertionError(f"Unexpected tool: {name}")

        mock_guarded_tool_call.side_effect = fake_tool_call

        context = build_assistant_prompt_context(
            surface="assistant_web",
            user_input="How does ClarityClaw compare to OpenClaw?",
            agent_name="researcher",
        )

        self.assertTrue(any(entry["source"] == "https://docs.openclaw.ai/" for entry in context))
        structure = next(entry for entry in context if entry["source"] == "answer_structure")
        self.assertIn("Similarities", structure["content"])
        self.assertIn("Gaps", structure["content"])

    @patch("runtime.assistant_grounding.guarded_tool_call")
    def test_build_assistant_prompt_context_adds_plan_structure_for_planning_question(self, mock_guarded_tool_call) -> None:
        def fake_tool_call(agent_name: str, name: str, args: dict | None = None) -> dict | None:
            self.assertEqual(agent_name, "researcher")
            if name == "search_files":
                return {"ok": True, "output": {"value": {"hits": []}}}
            if name == "fetch_url":
                return None
            raise AssertionError(f"Unexpected tool: {name}")

        mock_guarded_tool_call.side_effect = fake_tool_call

        context = build_assistant_prompt_context(
            surface="assistant_web",
            user_input="What should the next milestone prioritize and how should we plan v1.3?",
            agent_name="researcher",
        )

        structure = next(entry for entry in context if entry["source"] == "answer_structure")
        self.assertIn("Objective", structure["content"])
        self.assertIn("Next slices", structure["content"])

    @patch("runtime.assistant_grounding.guarded_tool_call")
    def test_build_assistant_prompt_context_adds_summary_structure_for_summary_question(self, mock_guarded_tool_call) -> None:
        def fake_tool_call(agent_name: str, name: str, args: dict | None = None) -> dict | None:
            self.assertEqual(agent_name, "researcher")
            if name == "search_files":
                return {"ok": True, "output": {"value": {"hits": []}}}
            if name == "fetch_url":
                return None
            raise AssertionError(f"Unexpected tool: {name}")

        mock_guarded_tool_call.side_effect = fake_tool_call

        context = build_assistant_prompt_context(
            surface="assistant_web",
            user_input="Summarize what v1.4 improved in ClarityClaw.",
            agent_name="researcher",
        )

        structure = next(entry for entry in context if entry["source"] == "answer_structure")
        self.assertIn("Concrete improvements", structure["content"])
        guidance = next(entry for entry in context if entry["source"] == "assistant_profile")
        self.assertIn("do not jump to future milestones", guidance["content"])
        self.assertTrue(any(entry["source"] == "docs/history/v1.4.md" for entry in context))
        milestone = next(entry for entry in context if entry["source"] == "docs/history/v1.4.md")
        self.assertIn("explicit domain-split tool layer", milestone["content"])

    @patch("runtime.assistant_grounding.guarded_tool_call")
    def test_build_assistant_prompt_context_skips_tools_for_non_project_question(self, mock_guarded_tool_call) -> None:
        context = build_assistant_prompt_context(
            surface="assistant_web",
            user_input="What is 2 plus 2?",
            agent_name="researcher",
        )

        self.assertEqual(context, [])
        mock_guarded_tool_call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
