import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gitlab


class NotePermissionStatsTests(unittest.TestCase):
    def test_sync_comments_inaccessible_source_notes_increments_stats(self):
        from app.services.sync_service import SyncService

        svc = SyncService(db=object())

        # Source client raises 403 when fetching notes
        source_client = Mock()
        source_client.get_issue_notes.side_effect = gitlab.exceptions.GitlabGetError(
            "forbidden", 403
        )

        target_client = Mock()

        stats = {"skipped_inaccessible": 0, "skipped_notes_inaccessible": 0}

        with patch.object(svc, "_get_client", return_value=source_client, autospec=True):
            svc._sync_comments(
                source_issue=SimpleNamespace(iid=1, project_id="sproj"),
                target_issue=SimpleNamespace(iid=2),
                source_instance=SimpleNamespace(id=1, url="https://src"),
                target_client=target_client,
                target_project_id="tproj",
                target_instance_id=2,
                source_project_id="sproj",
                stats=stats,
            )

        self.assertEqual(stats["skipped_inaccessible"], 1)
        self.assertEqual(stats["skipped_notes_inaccessible"], 1)
        # Should return early and never attempt to fetch target notes
        target_client.get_issue_notes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
