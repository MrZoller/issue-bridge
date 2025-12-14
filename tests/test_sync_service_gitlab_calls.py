import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class SyncServiceGitLabCallTests(unittest.TestCase):
    def test_ensure_labels_creates_missing_only(self):
        from app.services.sync_service import SyncService

        svc = SyncService(db=Mock())
        client = Mock()
        client.get_project_labels.return_value = [SimpleNamespace(name="bug")]

        svc._ensure_labels(client, "proj", ["bug", "enhancement"])

        client.get_project_labels.assert_called_once_with("proj")
        client.create_label.assert_called_once_with("proj", "enhancement")

    def test_ensure_milestone_returns_existing_id(self):
        from app.services.sync_service import SyncService

        svc = SyncService(db=Mock())
        client = Mock()
        client.get_project_milestones.return_value = [SimpleNamespace(title="v1", id=123)]

        out = svc._ensure_milestone(client, "proj", "v1")

        self.assertEqual(out, 123)
        client.create_milestone.assert_not_called()

    def test_ensure_milestone_creates_if_missing(self):
        from app.services.sync_service import SyncService

        svc = SyncService(db=Mock())
        client = Mock()
        client.get_project_milestones.return_value = []
        client.create_milestone.return_value = SimpleNamespace(id=999)

        out = svc._ensure_milestone(client, "proj", "v2")

        self.assertEqual(out, 999)
        client.create_milestone.assert_called_once_with("proj", {"title": "v2"})

    def test_ensure_milestone_returns_none_on_empty_title(self):
        from app.services.sync_service import SyncService

        svc = SyncService(db=Mock())
        client = Mock()

        self.assertIsNone(svc._ensure_milestone(client, "proj", ""))
        self.assertIsNone(svc._ensure_milestone(client, "proj", None))
        client.get_project_milestones.assert_not_called()

    def test_sync_comments_calls_expected_gitlab_methods(self):
        from app.services.sync_service import SyncService

        svc = SyncService(db=Mock())

        # source notes
        n1 = SimpleNamespace(system=True, author={"username": "bot"}, body="sys")
        n2 = SimpleNamespace(id=2, system=False, author={"username": "alice"}, body="hello")
        n3 = SimpleNamespace(id=3, system=False, author=None, body="world")

        source_client = Mock()
        source_client.get_issue_notes.return_value = [n1, n2, n3]

        target_client = Mock()
        # existing note body contains marker for alice note -> should dedupe
        existing = SimpleNamespace(
            body="**Comment by @alice:**\n\nhello\n\n---\n"
            + SyncService._note_marker(
                source_instance_url="https://src",
                source_project_id="sproj",
                source_issue_iid=7,
                source_note_id=2,
            )
        )
        target_client.get_issue_notes.return_value = [existing]

        with patch.object(svc, "_get_client", return_value=source_client, autospec=True):
            svc._sync_comments(
                source_issue=SimpleNamespace(iid=7, project_id="ignored"),
                target_issue=SimpleNamespace(iid=9),
                source_instance=SimpleNamespace(id=1, url="https://src"),
                target_client=target_client,
                target_project_id="tproj",
                target_instance_id=2,
                source_project_id="sproj",
            )

        source_client.get_issue_notes.assert_called_once_with("sproj", 7)
        target_client.get_issue_notes.assert_called_once_with("tproj", 9)
        # n1 skipped (system); n2 skipped (duplicate marker); n3 created with unknown author + marker
        target_client.create_issue_note.assert_called_once_with(
            "tproj",
            9,
            "**Comment by @unknown:**\n\nworld\n\n---\n"
            + SyncService._note_marker(
                source_instance_url="https://src",
                source_project_id="sproj",
                source_issue_iid=7,
                source_note_id=3,
            ),
        )


if __name__ == "__main__":
    unittest.main()
