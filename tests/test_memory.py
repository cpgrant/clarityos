import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime.memory as memory


class MemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.memory_dir = self.root_dir / "memories"
        self.memory_dir.mkdir()
        self.memory_dir_patcher = patch.object(memory, "MEMORY_DIR", self.memory_dir)
        self.memory_dir_patcher.start()

    def tearDown(self) -> None:
        self.memory_dir_patcher.stop()
        self.temp_dir.cleanup()

    def test_create_fact_memory_round_trip(self) -> None:
        saved = memory.create_memory(
            memory_type="fact",
            scope_kind="agent",
            agent="researcher",
            payload={"statement": "The queue is durable", "subject": "queue"},
            tags=["runtime", "runtime", "fact"],
            metadata={"source": "seed"},
        )

        loaded = memory.load_memory(saved["memory_id"])

        self.assertEqual(loaded["memory_type"], "fact")
        self.assertEqual(loaded["scope"], {"kind": "agent", "value": "researcher"})
        self.assertEqual(loaded["payload"]["statement"], "The queue is durable")
        self.assertEqual(loaded["payload"]["subject"], "queue")
        self.assertEqual(loaded["tags"], ["runtime", "fact"])
        self.assertEqual(memory.memory_summary(loaded)["memory_id"], saved["memory_id"])

    def test_create_memory_persists_versioned_state_envelope(self) -> None:
        saved = memory.create_memory(
            memory_type="fact",
            scope_kind="global",
            payload={"statement": "The queue is durable"},
        )

        with (self.memory_dir / f"{saved['memory_id']}.json").open(encoding="utf-8") as file:
            persisted = json.load(file)

        self.assertEqual(persisted["schema"], "memory.v1")
        self.assertEqual(persisted["version"], "v0.9")
        self.assertEqual(persisted["payload"]["memory_id"], saved["memory_id"])

    def test_load_memory_accepts_legacy_unversioned_snapshot(self) -> None:
        legacy_memory = {
            "memory_id": "legacy-memory",
            "memory_type": "fact",
            "scope": {"kind": "global", "value": None},
            "agent": None,
            "workflow_id": None,
            "run_id": None,
            "payload": {"statement": "Legacy memory"},
            "tags": [],
            "metadata": {},
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

        with (self.memory_dir / "legacy-memory.json").open("w", encoding="utf-8") as file:
            json.dump(legacy_memory, file, indent=2)

        loaded = memory.load_memory("legacy-memory")

        self.assertEqual(loaded["memory_id"], "legacy-memory")
        self.assertEqual(loaded["payload"]["statement"], "Legacy memory")

    def test_list_and_query_memories_support_mixed_legacy_and_versioned_snapshots(self) -> None:
        versioned = memory.create_memory(
            memory_type="summary",
            scope_kind="workflow",
            workflow_id="wf-1",
            payload={"text": "versioned workflow summary"},
            tags=["keep"],
        )
        legacy_memory = {
            "memory_id": "legacy-memory",
            "memory_type": "summary",
            "scope": {"kind": "workflow", "value": "wf-1"},
            "agent": None,
            "workflow_id": "wf-1",
            "run_id": None,
            "payload": {"text": "legacy workflow summary"},
            "tags": ["keep"],
            "metadata": {},
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        with (self.memory_dir / "legacy-memory.json").open("w", encoding="utf-8") as file:
            json.dump(legacy_memory, file, indent=2)

        listed = memory.list_memories(scope_kind="workflow", workflow_id="wf-1", tags=["keep"])
        queried = memory.query_memories(query="workflow summary", scope_kind="workflow", workflow_id="wf-1", tags=["keep"])

        listed_ids = {item["memory_id"] for item in listed}
        queried_ids = {item["memory_id"] for item in queried["results"]}
        self.assertIn(versioned["memory_id"], listed_ids)
        self.assertIn("legacy-memory", listed_ids)
        self.assertIn(versioned["memory_id"], queried_ids)
        self.assertIn("legacy-memory", queried_ids)

    def test_update_memory_rewrites_legacy_snapshot_as_versioned_state(self) -> None:
        legacy_memory = {
            "memory_id": "legacy-memory",
            "memory_type": "summary",
            "scope": {"kind": "global", "value": None},
            "agent": None,
            "workflow_id": None,
            "run_id": None,
            "payload": {"text": "legacy summary"},
            "tags": [],
            "metadata": {},
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        path = self.memory_dir / "legacy-memory.json"
        with path.open("w", encoding="utf-8") as file:
            json.dump(legacy_memory, file, indent=2)

        updated = memory.update_memory("legacy-memory", payload={"text": "rewritten summary"})

        self.assertEqual(updated["payload"]["text"], "rewritten summary")
        with path.open(encoding="utf-8") as file:
            saved = json.load(file)
        self.assertEqual(saved["schema"], "memory.v1")

    def test_create_artifact_ref_memory_round_trip(self) -> None:
        saved = memory.create_memory(
            memory_type="artifact_ref",
            scope_kind="workflow",
            workflow_id="wf-123",
            payload={"artifact_id": "artifact-123", "description": "final answer"},
            metadata={"kind": "tool_output"},
        )

        loaded = memory.load_memory(saved["memory_id"])

        self.assertEqual(loaded["memory_type"], "artifact_ref")
        self.assertEqual(loaded["scope"], {"kind": "workflow", "value": "wf-123"})
        self.assertEqual(loaded["payload"]["artifact_id"], "artifact-123")
        self.assertEqual(loaded["payload"]["description"], "final answer")

    def test_list_memories_filters_by_scope_type_and_tags(self) -> None:
        memory.create_memory(
            memory_type="fact",
            scope_kind="agent",
            agent="default",
            payload={"statement": "one"},
            tags=["keep", "agent"],
        )
        memory.create_memory(
            memory_type="summary",
            scope_kind="workflow",
            workflow_id="wf-1",
            payload={"text": "workflow summary"},
            tags=["keep", "workflow"],
        )
        memory.create_memory(
            memory_type="observation",
            scope_kind="workflow",
            workflow_id="wf-1",
            payload={"text": "workflow observation"},
            tags=["workflow"],
        )

        workflow_memories = memory.list_memories(scope_kind="workflow", workflow_id="wf-1")
        tagged_summaries = memory.list_memories(memory_type="summary", tags=["keep"])

        self.assertEqual(len(workflow_memories), 2)
        self.assertEqual(len(tagged_summaries), 1)
        self.assertEqual(tagged_summaries[0]["memory_type"], "summary")

    def test_update_memory_rewrites_payload_and_updated_at(self) -> None:
        saved = memory.create_memory(
            memory_type="summary",
            scope_kind="agent",
            agent="default",
            payload={"text": "first summary"},
        )

        with patch.object(memory, "utc_now", return_value="2026-04-07T12:00:00+00:00"):
            updated = memory.update_memory(
                saved["memory_id"],
                payload={"text": "updated summary", "source": "operator"},
                tags=["fresh"],
                metadata={"revised": True},
            )

        self.assertEqual(updated["payload"]["text"], "updated summary")
        self.assertEqual(updated["payload"]["source"], "operator")
        self.assertEqual(updated["tags"], ["fresh"])
        self.assertEqual(updated["metadata"], {"revised": True})
        self.assertEqual(updated["created_at"], saved["created_at"])
        self.assertEqual(updated["updated_at"], "2026-04-07T12:00:00+00:00")

    def test_query_memories_returns_ranked_source_summaries(self) -> None:
        memory.create_memory(
            memory_type="fact",
            scope_kind="agent",
            agent="researcher",
            payload={"statement": "The queue is durable and supports retries", "subject": "queue"},
            tags=["runtime", "queue"],
        )
        memory.create_memory(
            memory_type="summary",
            scope_kind="agent",
            agent="researcher",
            payload={"text": "Retry behavior depends on backoff settings", "source": "worker tests"},
            tags=["retry"],
        )
        memory.create_memory(
            memory_type="observation",
            scope_kind="workflow",
            workflow_id="wf-1",
            payload={"text": "Artifacts were saved after completion"},
            tags=["artifact"],
        )

        result = memory.query_memories(query="queue retry", agent="researcher", limit=2, max_chars=400)

        self.assertEqual(result["result_count"], 2)
        self.assertEqual(result["results"][0]["memory_type"], "fact")
        self.assertIn("queue", result["results"][0]["matched_terms"])
        self.assertIn("summary", result["results"][1]["memory_type"])
        self.assertNotIn("payload", result["results"][0])
        self.assertLessEqual(result["used_chars"], 400)

    def test_query_memories_respects_scope_filters_and_tag_filters(self) -> None:
        memory.create_memory(
            memory_type="summary",
            scope_kind="workflow",
            workflow_id="wf-1",
            payload={"text": "workflow one summary"},
            tags=["keep"],
        )
        memory.create_memory(
            memory_type="summary",
            scope_kind="workflow",
            workflow_id="wf-2",
            payload={"text": "workflow two summary"},
            tags=["keep"],
        )
        memory.create_memory(
            memory_type="summary",
            scope_kind="workflow",
            workflow_id="wf-1",
            payload={"text": "workflow one internal note"},
            tags=["skip"],
        )

        result = memory.query_memories(
            query="workflow summary",
            scope_kind="workflow",
            workflow_id="wf-1",
            tags=["keep"],
        )

        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["results"][0]["workflow_id"], "wf-1")
        self.assertEqual(result["results"][0]["tags"], ["keep"])

    def test_query_memories_respects_limit_and_total_char_budget(self) -> None:
        memory.create_memory(
            memory_type="summary",
            scope_kind="global",
            payload={"text": "queue queue queue queue queue queue queue queue queue queue"},
        )
        memory.create_memory(
            memory_type="summary",
            scope_kind="global",
            payload={"text": "queue summary with more details about retries and workers"},
        )
        memory.create_memory(
            memory_type="summary",
            scope_kind="global",
            payload={"text": "queue durability note with extra explanation"},
        )

        result = memory.query_memories(
            query="queue",
            limit=3,
            max_chars=50,
            max_summary_chars=50,
        )

        self.assertEqual(result["result_count"], 1)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(result["used_chars"], 50)

    def test_query_memories_rejects_blank_query(self) -> None:
        with self.assertRaisesRegex(ValueError, "Memory `query` must be a non-empty string"):
            memory.query_memories(query="   ")

    def test_query_memories_rejects_non_searchable_query(self) -> None:
        with self.assertRaisesRegex(ValueError, "must contain searchable text"):
            memory.query_memories(query="???")

    def test_delete_memory_removes_saved_file(self) -> None:
        saved = memory.create_memory(
            memory_type="observation",
            scope_kind="run",
            run_id="run-123",
            payload={"text": "saw a retry"},
        )

        deleted = memory.delete_memory(saved["memory_id"])

        self.assertEqual(deleted["memory_id"], saved["memory_id"])
        with self.assertRaises(FileNotFoundError):
            memory.load_memory(saved["memory_id"])

    def test_create_memory_rejects_unknown_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown memory type"):
            memory.create_memory(
                memory_type="note",
                scope_kind="agent",
                agent="default",
                payload={"text": "bad"},
            )

    def test_create_memory_rejects_missing_scope_reference(self) -> None:
        with self.assertRaisesRegex(ValueError, "Memory `agent` must be a non-empty string"):
            memory.create_memory(
                memory_type="fact",
                scope_kind="agent",
                payload={"statement": "missing agent"},
            )

    def test_create_memory_rejects_unknown_payload_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            memory.create_memory(
                memory_type="fact",
                scope_kind="global",
                payload={"statement": "ok", "extra": "nope"},
            )


if __name__ == "__main__":
    unittest.main()
