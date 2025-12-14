import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class SyncMarkersAndCommentLoopPreventionTests(unittest.TestCase):
    def test_issue_marker_roundtrip(self):
        from app.services.sync_service import SyncService

        marker = SyncService._issue_marker_with_fields(
            source_instance_url="https://gitlab.example/",
            source_project_id="group/proj",
            source_issue_iid=123,
            issue_type="incident",
            milestone_title="M1",
            iteration_title="Sprint 1",
            iteration_start_date="2025-01-01",
            iteration_due_date="2025-01-14",
            epic_title="Epic A",
        )
        desc = "hello\n\n---\n*Synced from: https://gitlab.example/-/issues/123*\n" + marker

        parsed = SyncService._parse_issue_marker(desc)
        self.assertEqual(parsed, ("https://gitlab.example", "group/proj", 123))

        payload = SyncService._parse_issue_marker_payload(desc)
        self.assertEqual(payload.get("issue_type"), "incident")
        self.assertEqual(payload.get("milestone_title"), "M1")
        self.assertEqual(payload.get("iteration_title"), "Sprint 1")
        self.assertEqual(payload.get("epic_title"), "Epic A")

        ref = SyncService._parse_sync_reference(desc)
        self.assertEqual(ref, ("https://gitlab.example", 123))

    def test_sync_comments_dedupes_by_note_marker_and_skips_loop_notes(self):
        from app.services.sync_service import SyncService

        svc = SyncService(db=SimpleNamespace())

        source_instance = SimpleNamespace(id=1, url="https://src")
        source_issue = SimpleNamespace(iid=7, project_id="sproj")
        target_issue = SimpleNamespace(iid=9)

        # Source notes: one normal, one that already contains our sync marker (loop note)
        normal = SimpleNamespace(
            id=101,
            system=False,
            author={"username": "alice"},
            body="hello",
        )
        loop = SimpleNamespace(
            id=202,
            system=False,
            author={"username": "syncbot"},
            body="something\n\n---\n<!-- gl-issue-sync-note:AAAA -->",
        )

        source_client = SimpleNamespace(get_issue_notes=lambda project_id, iid: [normal, loop])

        # Target already has note marker for the normal note, so it should not be re-created.
        existing_body = "**Comment by @alice:**\n\nhello\n\n---\n" + SyncService._note_marker(
            source_instance_url="https://src",
            source_project_id="sproj",
            source_issue_iid=7,
            source_note_id=101,
        )
        target_client = SimpleNamespace(
            get_issue_notes=lambda project_id, iid: [SimpleNamespace(body=existing_body)],
            create_issue_note=Mock(),
        )

        with patch.object(svc, "_get_client", return_value=source_client, autospec=True):
            svc._sync_comments(
                source_issue=source_issue,
                target_issue=target_issue,
                source_instance=source_instance,
                target_client=target_client,
                target_project_id="tproj",
                target_instance_id=2,
                source_project_id="sproj",
            )

        target_client.create_issue_note.assert_not_called()


if __name__ == "__main__":
    unittest.main()
