import logging
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

logging.disable(logging.CRITICAL)


class _FakeQuery:
    def __init__(self, session):
        self._session = session

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if not self._session._first_queue:
            return None
        return self._session._first_queue.pop(0)


class _FakeSession:
    def __init__(self, first_queue=None):
        self._first_queue = list(first_queue or [])
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, _model):
        return _FakeQuery(self)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class SyncServiceAdditionalBehaviorTests(unittest.TestCase):
    def test_add_sync_reference_normalizes_instance_url(self):
        from app.services.sync_service import SyncService

        svc = SyncService(_FakeSession())
        desc = svc._add_sync_reference("hello", "https://gitlab.example/", 12)
        self.assertIn("https://gitlab.example/-/issues/12", desc)
        self.assertNotIn("https://gitlab.example//-/issues/12", desc)

    def test_issue_hash_ignores_updated_at(self):
        from app.services.sync_service import SyncService

        svc = SyncService(_FakeSession())
        i1 = SimpleNamespace(
            title="t",
            description="d",
            state="opened",
            labels=["a"],
            updated_at="2025-01-01T00:00:00Z",
            assignees=[],
            milestone=None,
            due_date=None,
        )
        i2 = SimpleNamespace(
            title="t",
            description="d",
            state="opened",
            labels=["a"],
            updated_at="2025-02-01T00:00:00Z",
            assignees=[],
            milestone=None,
            due_date=None,
        )

        self.assertEqual(svc._compute_issue_hash(i1), svc._compute_issue_hash(i2))

    def test_comment_only_updates_sync_comments_without_issue_update(self):
        from app.models.sync_log import SyncDirection
        from app.services.sync_service import SyncService

        # existing mapping
        synced_issue = SimpleNamespace(
            id=1,
            project_pair_id=1,
            source_issue_iid=7,
            source_issue_id=700,
            target_issue_iid=9,
            target_issue_id=900,
            last_synced_at=None,
            sync_hash="hash",
        )

        db = _FakeSession(first_queue=[synced_issue])
        svc = SyncService(db)

        source_issue = SimpleNamespace(
            iid=7,
            id=700,
            title="A",
            description="B",
            labels=[],
            state="opened",
            updated_at="2025-01-01T00:00:00Z",
            assignees=[],
            milestone=None,
            due_date=None,
        )

        class _SourceClient:
            def get_issues(self, project_id, updated_after=None):
                return [source_issue]

        class _TargetClient:
            def get_issue_optional(self, project_id, issue_iid):
                return SimpleNamespace(
                    iid=9, id=900, state="opened", updated_at="2025-01-01T00:00:00Z"
                ), None

        with (
            patch.object(svc, "_compute_issue_hash", return_value="hash", autospec=True),
            patch.object(svc, "_update_issue_from_source", autospec=True) as upd,
            patch.object(svc, "_sync_comments", autospec=True) as sync_comments,
        ):
            stats = svc._sync_direction(
                project_pair=SimpleNamespace(id=1),
                source_client=_SourceClient(),
                target_client=_TargetClient(),
                source_project_id="sproj",
                target_project_id="tproj",
                source_instance=SimpleNamespace(id=10, url="https://src"),
                target_instance=SimpleNamespace(id=20, url="https://tgt"),
                direction=SyncDirection.SOURCE_TO_TARGET,
                updated_after=None,
            )

        # Since last_synced_at is None, we will still treat as needing work; but content hash matches,
        # so we should not call the issue update.
        upd.assert_not_called()
        sync_comments.assert_called()
        self.assertEqual(stats["updated"], 1)

    def test_rebuilds_mapping_from_sync_reference_in_description(self):
        from app.models.sync_log import SyncDirection
        from app.services.sync_service import SyncService

        db = _FakeSession(first_queue=[None])
        svc = SyncService(db)

        # This issue appears on the SOURCE side, but was created by syncing from the TARGET side.
        mirrored = SimpleNamespace(
            iid=7,
            id=700,
            title="A",
            description="X\n\n---\n*Synced from: https://tgt/-/issues/99*",
            labels=[],
            state="opened",
            updated_at="2025-01-01T00:00:00Z",
            assignees=[],
            milestone=None,
            due_date=None,
        )

        class _SourceClient:
            def get_issues(self, project_id, updated_after=None):
                return [mirrored]

        class _TargetClient:
            def get_issue_optional(self, project_id, issue_iid):
                if issue_iid == 99:
                    return SimpleNamespace(iid=99, id=9900), None
                return None, 404

        with (
            patch.object(svc, "_compute_issue_hash", return_value="hash", autospec=True),
            patch.object(svc, "_create_issue_from_source", autospec=True) as create_call,
        ):
            stats = svc._sync_direction(
                project_pair=SimpleNamespace(id=1),
                source_client=_SourceClient(),
                target_client=_TargetClient(),
                source_project_id="sproj",
                target_project_id="tproj",
                source_instance=SimpleNamespace(id=10, url="https://src"),
                target_instance=SimpleNamespace(id=20, url="https://tgt"),
                direction=SyncDirection.SOURCE_TO_TARGET,
                updated_after=None,
            )

        # mapping created, no new issue should be created
        create_call.assert_not_called()
        self.assertEqual(stats["created"], 1)
        self.assertEqual(len(db.added), 1)
        added = db.added[0]
        self.assertEqual(getattr(added, "source_issue_iid"), 7)
        self.assertEqual(getattr(added, "target_issue_iid"), 99)

    def test_conflict_detection_ignores_comment_only_updates_via_hash_baseline(self):
        from app.services.sync_service import SyncService

        svc = SyncService(_FakeSession())

        synced_issue = SimpleNamespace(
            last_synced_at=datetime(2025, 1, 1, 0, 0, 0),
            sync_hash="baseline",
        )
        # Both updated after last sync.
        source_issue = SimpleNamespace(updated_at="2025-01-02T00:00:00Z")
        target_issue = SimpleNamespace(updated_at="2025-01-02T00:00:00Z")

        def _hash_side_effect(issue):
            # Pretend the source content hasn't changed (comment-only), but target did.
            if issue is source_issue:
                return "baseline"
            return "changed"

        with patch(
            "app.services.sync_service.SyncService._compute_issue_hash",
            side_effect=_hash_side_effect,
        ):
            self.assertEqual(svc._compute_issue_hash(source_issue), "baseline")
            self.assertEqual(svc._compute_issue_hash(target_issue), "changed")
            self.assertFalse(svc._detect_conflict(synced_issue, source_issue, target_issue))


if __name__ == "__main__":
    unittest.main()
