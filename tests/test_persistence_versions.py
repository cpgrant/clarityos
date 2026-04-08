import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime.approval as approval
import runtime.artifact as artifact
import runtime.state as state


class PersistenceVersionTests(unittest.TestCase):
    def test_parse_state_version_rejects_invalid_version_format(self) -> None:
        with self.assertRaisesRegex(ValueError, "must match `v<major>.<minor>`"):
            state.parse_state_version("0.9")

    def test_unwrap_state_payload_rejects_future_version(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "Persisted state version `v9.9` is newer than supported version `v0.9`",
        ):
            state.unwrap_state_payload(
                {
                    "schema": "workflow.v1",
                    "version": "v9.9",
                    "payload": {"workflow_id": "wf-123"},
                },
                schema="workflow.v1",
            )

    def test_unwrap_state_payload_rejects_schema_mismatch(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "Persisted state schema mismatch: expected `workflow.v1`, got `job.v1`",
        ):
            state.unwrap_state_payload(
                {
                    "schema": "job.v1",
                    "version": "v0.9",
                    "payload": {"job_id": "job-123"},
                },
                schema="workflow.v1",
            )

    def test_migrate_state_payload_rewrites_legacy_state_in_place(self) -> None:
        path = self.root_dir / "legacy.json"
        with path.open("w", encoding="utf-8") as file:
            json.dump({"workflow_id": "wf-123", "status": "running"}, file, indent=2)

        migrated = state.migrate_state_payload(path, schema="workflow.v1")

        self.assertTrue(migrated["migrated"])
        self.assertTrue(migrated["before"]["legacy_format"])
        self.assertFalse(migrated["after"]["legacy_format"])
        self.assertEqual(migrated["after"]["schema"], "workflow.v1")
        self.assertEqual(migrated["after"]["version"], "v0.9")

    def test_migrate_state_payload_is_noop_for_supported_versioned_state(self) -> None:
        path = self.root_dir / "versioned.json"
        with path.open("w", encoding="utf-8") as file:
            json.dump(
                {
                    "schema": "workflow.v1",
                    "version": "v0.9",
                    "payload": {"workflow_id": "wf-123"},
                },
                file,
                indent=2,
            )

        migrated = state.migrate_state_payload(path, schema="workflow.v1")

        self.assertFalse(migrated["migrated"])
        self.assertFalse(migrated["before"]["legacy_format"])

    def test_migrate_state_directory_rewrites_only_legacy_files_by_default(self) -> None:
        with (self.root_dir / "legacy.json").open("w", encoding="utf-8") as file:
            json.dump({"workflow_id": "wf-legacy"}, file, indent=2)
        with (self.root_dir / "versioned.json").open("w", encoding="utf-8") as file:
            json.dump(
                {
                    "schema": "workflow.v1",
                    "version": "v0.9",
                    "payload": {"workflow_id": "wf-versioned"},
                },
                file,
                indent=2,
            )

        migrated = state.migrate_state_directory(self.root_dir, schema="workflow.v1")

        self.assertEqual(migrated["processed_count"], 2)
        self.assertEqual(migrated["migrated_count"], 1)
        self.assertEqual(migrated["unchanged_count"], 1)
        self.assertEqual([item["state_id"] for item in migrated["results"]], ["legacy"])

    def test_migrate_state_directory_can_include_unchanged_results(self) -> None:
        with (self.root_dir / "versioned.json").open("w", encoding="utf-8") as file:
            json.dump(
                {
                    "schema": "workflow.v1",
                    "version": "v0.9",
                    "payload": {"workflow_id": "wf-versioned"},
                },
                file,
                indent=2,
            )

        migrated = state.migrate_state_directory(
            self.root_dir,
            schema="workflow.v1",
            include_unchanged=True,
        )

        self.assertEqual(migrated["processed_count"], 1)
        self.assertEqual(migrated["unchanged_count"], 1)
        self.assertEqual(migrated["results"][0]["state_id"], "versioned")

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.approval_dir = self.root_dir / "approvals"
        self.artifact_dir = self.root_dir / "artifacts"
        self.approval_dir.mkdir()
        self.artifact_dir.mkdir()
        self.approval_dir_patcher = patch.object(approval, "APPROVAL_DIR", self.approval_dir)
        self.artifact_dir_patcher = patch.object(artifact, "ARTIFACT_DIR", self.artifact_dir)
        self.approval_dir_patcher.start()
        self.artifact_dir_patcher.start()

    def tearDown(self) -> None:
        self.approval_dir_patcher.stop()
        self.artifact_dir_patcher.stop()
        self.temp_dir.cleanup()

    def test_create_approval_persists_versioned_state_envelope(self) -> None:
        created = approval.create_approval(
            run_id="run-123",
            workflow_id="wf-123",
            agent="default",
            policy_name="approval_exec",
            action={"capability": "exec", "tool": "echo", "command": "echo", "path": None},
            reason="needs approval",
            request={"input": "hello", "agent": "default", "tool": "echo", "tool_args": {"text": "hello"}},
        )

        with (self.approval_dir / f"{created['approval_id']}.json").open(encoding="utf-8") as file:
            saved = json.load(file)

        self.assertEqual(saved["schema"], "approval.v1")
        self.assertEqual(saved["version"], "v0.9")
        self.assertEqual(saved["payload"]["approval_id"], created["approval_id"])

    def test_get_approval_accepts_legacy_unversioned_snapshot(self) -> None:
        legacy_approval = {
            "approval_id": "approval-legacy",
            "status": "pending",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "requested_run_id": "run-123",
            "workflow_id": "wf-123",
            "resumed_run_id": None,
            "agent": "default",
            "policy": "approval_exec",
            "action": {"capability": "exec", "tool": "echo", "command": "echo", "path": None},
            "reason": "needs approval",
            "request": {"input": "", "agent": "default", "tool": "echo", "tool_args": {"text": "hello"}},
            "history": [],
        }

        with (self.approval_dir / "approval-legacy.json").open("w", encoding="utf-8") as file:
            json.dump(legacy_approval, file, indent=2)

        loaded = approval.get_approval("approval-legacy")

        self.assertEqual(loaded["approval_id"], "approval-legacy")
        self.assertEqual(loaded["status"], "pending")

    def test_create_artifact_persists_versioned_state_envelope(self) -> None:
        created = artifact.create_artifact(
            workflow_id="wf-123",
            run_id="run-123",
            name="result",
            kind="model_output",
            value="hello",
            metadata={"model": "fake"},
        )

        with (self.artifact_dir / f"{created['artifact_id']}.json").open(encoding="utf-8") as file:
            saved = json.load(file)

        self.assertEqual(saved["schema"], "artifact.v1")
        self.assertEqual(saved["version"], "v0.9")
        self.assertEqual(saved["payload"]["artifact_id"], created["artifact_id"])

    def test_load_artifact_accepts_legacy_unversioned_snapshot(self) -> None:
        legacy_artifact = {
            "artifact_id": "artifact-legacy",
            "workflow_id": "wf-123",
            "run_id": "run-123",
            "name": "result",
            "kind": "model_output",
            "value": "hello",
            "metadata": {},
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

        with (self.artifact_dir / "artifact-legacy.json").open("w", encoding="utf-8") as file:
            json.dump(legacy_artifact, file, indent=2)

        loaded = artifact.load_artifact("artifact-legacy")

        self.assertEqual(loaded["artifact_id"], "artifact-legacy")
        self.assertEqual(loaded["kind"], "model_output")
