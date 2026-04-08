import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.session import (
    archive_session,
    append_session_message,
    create_session,
    list_sessions,
    load_session,
    prune_sessions,
    session_token_hash,
    verify_session_access,
    write_session,
)


class SessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.session_dir = self.root_dir / "sessions"
        self.session_dir.mkdir()
        self.session_dir_patcher = patch("runtime.session.SESSION_DIR", self.session_dir)
        self.session_dir_patcher.start()

    def tearDown(self) -> None:
        self.session_dir_patcher.stop()
        self.temp_dir.cleanup()

    def test_create_session_persists_versioned_state_envelope(self) -> None:
        session = create_session(title="Inbox", agent="default")

        path = self.session_dir / f"{session['session_id']}.json"
        with path.open(encoding="utf-8") as file:
            saved = json.load(file)

        self.assertEqual(saved["schema"], "session.v1")
        self.assertEqual(saved["version"], "v0.9")
        self.assertEqual(saved["payload"]["status"], "open")
        self.assertEqual(saved["payload"]["memory_scope"]["kind"], "agent")
        self.assertTrue(saved["payload"]["ownership"]["auth_required"])
        self.assertEqual(
            saved["payload"]["ownership"]["token_hash"],
            session_token_hash(session["session_token"]),
        )
        self.assertNotIn("token_hash", session["ownership"])

    def test_load_session_accepts_legacy_unversioned_snapshot(self) -> None:
        legacy_snapshot = {
            "session_id": "legacy-session",
            "title": "Legacy",
            "agent": "default",
            "status": "open",
            "ownership": None,
            "memory_scope": {"kind": "agent", "value": "default"},
            "current_workflow_id": None,
            "workflow_ids": [],
            "last_run_id": None,
            "last_job_id": None,
            "messages": [],
            "metadata": {},
            "transition_history": [],
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

        with (self.session_dir / "legacy-session.json").open("w", encoding="utf-8") as file:
            json.dump(legacy_snapshot, file, indent=2)

        loaded = load_session("legacy-session")

        self.assertEqual(loaded.session_id, "legacy-session")
        self.assertEqual(loaded.status, "open")
        self.assertEqual(loaded.memory_scope["value"], "default")
        self.assertFalse(loaded.ownership["auth_required"])

    def test_verify_session_access_requires_valid_owned_session_token(self) -> None:
        session = create_session(title="Inbox", agent="default")
        loaded = load_session(session["session_id"])

        verify_session_access(loaded, session["session_token"])

        with self.assertRaises(PermissionError):
            verify_session_access(loaded, "wrong-token")

    def test_archive_session_marks_session_archived_with_reason(self) -> None:
        session = create_session(title="Inbox", agent="default")

        archived = archive_session(session["session_id"], reason="support cleanup")
        loaded = load_session(session["session_id"])

        self.assertEqual(archived["status"], "archived")
        self.assertEqual(loaded.status, "archived")
        self.assertEqual(loaded.metadata["maintenance"]["archive_reason"], "support cleanup")

    def test_prune_sessions_removes_old_archived_sessions(self) -> None:
        session = create_session(title="Inbox", agent="default")
        archive_session(session["session_id"], reason="cleanup")
        path = self.session_dir / f"{session['session_id']}.json"
        with path.open(encoding="utf-8") as file:
            saved = json.load(file)
        saved["payload"]["updated_at"] = "2026-01-01T00:00:00+00:00"
        with path.open("w", encoding="utf-8") as file:
            json.dump(saved, file, indent=2)

        result = prune_sessions(older_than_hours=1)

        self.assertEqual(result["pruned_count"], 1)
        self.assertEqual(result["pruned_session_ids"], [session["session_id"]])
        self.assertFalse((self.session_dir / f"{session['session_id']}.json").exists())

    @patch("runtime.session.start_workflow")
    def test_append_session_message_tracks_workflow_and_messages(self, mock_start_workflow) -> None:
        mock_start_workflow.return_value = {
            "status": "success",
            "output": "Hello back",
            "workflow": {
                "workflow_id": "wf-123",
                "run_id": "wf-123",
                "latest_run_id": "wf-123",
                "artifacts": [],
            },
            "job_id": "job-123",
            "worker_id": "worker-123",
        }
        session = create_session(agent="default")

        result = append_session_message(session["session_id"], content="Hello there")

        saved = load_session(session["session_id"])
        self.assertEqual(result["session"]["status"], "active")
        self.assertEqual(saved.current_workflow_id, "wf-123")
        self.assertEqual(saved.last_run_id, "wf-123")
        self.assertEqual(saved.last_job_id, "job-123")
        self.assertEqual(saved.workflow_ids, ["wf-123"])
        self.assertEqual(len(saved.messages), 2)
        self.assertEqual(saved.messages[0].role, "user")
        self.assertEqual(saved.messages[0].workflow_id, "wf-123")
        self.assertEqual(saved.messages[1].role, "assistant")
        self.assertEqual(saved.messages[1].content, "Hello back")
        self.assertEqual(saved.messages[1].status, "completed")

    @patch("runtime.session.start_workflow")
    def test_append_session_message_marks_recovered_after_waiting_session_succeeds(self, mock_start_workflow) -> None:
        mock_start_workflow.return_value = {
            "status": "pending",
            "output": None,
            "approval": {"approval_id": "approval-123"},
            "workflow": {
                "workflow_id": "wf-waiting",
                "run_id": "wf-waiting",
                "latest_run_id": "wf-waiting",
                "artifacts": [],
            },
        }
        session = create_session(agent="default")
        append_session_message(session["session_id"], content="Need approval")

        mock_start_workflow.return_value = {
            "status": "success",
            "output": "Recovered answer",
            "workflow": {
                "workflow_id": "wf-recovered",
                "run_id": "wf-recovered",
                "latest_run_id": "wf-recovered",
                "artifacts": [],
            },
        }
        result = append_session_message(session["session_id"], content="Try again")

        saved = load_session(session["session_id"])
        self.assertEqual(result["session"]["status"], "recovered")
        self.assertEqual(saved.status, "recovered")
        self.assertIn("wf-recovered", saved.workflow_ids)

    def test_list_sessions_filters_by_status(self) -> None:
        open_session = create_session(title="Open", agent="default")
        errored_session = load_session(open_session["session_id"])
        errored_session.status = "errored"
        write_session(errored_session)

        create_session(title="Fresh", agent="researcher")

        sessions = list_sessions(status="errored")

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["session_id"], open_session["session_id"])


if __name__ == "__main__":
    unittest.main()
