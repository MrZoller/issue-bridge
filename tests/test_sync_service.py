import unittest
from types import SimpleNamespace
from unittest.mock import patch


class _FakeQuery:
    def __init__(self, session):
        self._session = session

    def filter(self, *args, **kwargs):
        # We don't evaluate SQLAlchemy expressions in unit tests.
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

    def refresh(self, _obj):
        return None


class SyncServiceBehaviorTests(unittest.TestCase):
    def test_extract_username_accepts_dict_or_object(self):
        from app.services.sync_service import SyncService

        svc = SyncService(_FakeSession())

        self.assertEqual(svc._extract_username({"username": "alice"}), "alice")
        self.assertEqual(svc._extract_username(SimpleNamespace(username="bob")), "bob")
        self.assertIsNone(svc._extract_username({"nope": "x"}))

    def test_update_clears_removed_fields(self):
        from app.services.sync_service import SyncService

        db = _FakeSession()
        svc = SyncService(db)

        # Source issue with fields removed/empty
        source_issue = SimpleNamespace(
            iid=1,
            title="T",
            description="D",
            labels=[],
            assignees=[],
            milestone=None,
            due_date=None,
            state="opened",
        )

        target_issue = SimpleNamespace(iid=2, state="opened")

        class _TargetClient:
            def __init__(self):
                self.update_calls = []

            def get_issue(self, project_id, issue_iid):
                return target_issue

            def update_issue(self, project_id, issue_iid, issue_data):
                self.update_calls.append((project_id, issue_iid, issue_data))

        target_client = _TargetClient()

        with patch.object(svc, "_sync_comments", autospec=True):
            svc._update_issue_from_source(
                source_issue=source_issue,
                target_issue_iid=2,
                source_instance=SimpleNamespace(id=10, url="https://src"),
                target_client=target_client,
                target_project_id="tproj",
                target_instance_id=20,
                source_project_id="sproj",
            )

        self.assertEqual(len(target_client.update_calls), 1)
        _, _, payload = target_client.update_calls[0]

        self.assertIn("assignee_ids", payload)
        self.assertEqual(payload["assignee_ids"], [])
        self.assertIn("milestone_id", payload)
        self.assertEqual(payload["milestone_id"], 0)
        self.assertIn("due_date", payload)
        self.assertIsNone(payload["due_date"])

    def test_sync_direction_recreates_when_target_issue_missing(self):
        from app.services.sync_service import SyncService
        from app.models.sync_log import SyncDirection

        # First query for synced_issue returns an existing mapping.
        synced_issue = SimpleNamespace(
            id=123,
            project_pair_id=1,
            source_issue_iid=7,
            source_issue_id=700,
            target_issue_iid=9,
            target_issue_id=900,
            last_synced_at=None,
            sync_hash=None,
        )

        db = _FakeSession(first_queue=[synced_issue])
        svc = SyncService(db)

        source_issue = SimpleNamespace(
            iid=7,
            id=700,
            project_id="sproj",
            title="A",
            description="B",
            labels=[],
            assignees=[],
            milestone=None,
            due_date=None,
            state="opened",
            updated_at="2025-01-01T00:00:00Z",
        )

        class _SourceClient:
            def get_issues(self, project_id, updated_after=None):
                self.project_id = project_id
                self.updated_after = updated_after
                return [source_issue]

        class _TargetClient:
            def get_issue_optional(self, project_id, issue_iid):
                return None, 404

        recreated_issue = SimpleNamespace(iid=111, id=222)

        with patch.object(svc, "_create_issue_from_source", return_value=recreated_issue, autospec=True), \
             patch.object(svc, "_compute_synced_hash", return_value="hash", autospec=True):
            stats = svc._sync_direction(
                project_pair=SimpleNamespace(id=1),
                source_client=_SourceClient(),
                target_client=_TargetClient(),
                source_project_id="sproj",
                target_project_id="tproj",
                source_instance=SimpleNamespace(id=10, url="https://src"),
                target_instance=SimpleNamespace(id=20, url="https://tgt"),
                direction=SyncDirection.SOURCE_TO_TARGET,
            )

        self.assertEqual(stats["updated"], 1)
        self.assertEqual(synced_issue.target_issue_iid, 111)
        self.assertEqual(synced_issue.target_issue_id, 222)
        self.assertGreaterEqual(db.commits, 1)

    def test_sync_direction_does_not_recreate_on_target_403(self):
        from app.services.sync_service import SyncService
        from app.models.sync_log import SyncDirection

        synced_issue = SimpleNamespace(
            id=123,
            project_pair_id=1,
            source_issue_iid=7,
            source_issue_id=700,
            target_issue_iid=9,
            target_issue_id=900,
            last_synced_at=None,
            sync_hash=None,
        )
        db = _FakeSession(first_queue=[synced_issue])
        svc = SyncService(db)

        source_issue = SimpleNamespace(
            iid=7,
            id=700,
            project_id="sproj",
            title="A",
            description="B",
            labels=[],
            assignees=[],
            milestone=None,
            due_date=None,
            state="opened",
            updated_at="2025-01-01T00:00:00Z",
        )

        class _SourceClient:
            def get_issues(self, project_id, updated_after=None):
                return [source_issue]

        class _TargetClient:
            def get_issue_optional(self, project_id, issue_iid):
                return None, 403

        with patch.object(svc, "_create_issue_from_source", autospec=True) as create_call, \
             patch.object(svc, "_log_sync", autospec=True):
            stats = svc._sync_direction(
                project_pair=SimpleNamespace(id=1),
                source_client=_SourceClient(),
                target_client=_TargetClient(),
                source_project_id="sproj",
                target_project_id="tproj",
                source_instance=SimpleNamespace(id=10, url="https://src"),
                target_instance=SimpleNamespace(id=20, url="https://tgt"),
                direction=SyncDirection.SOURCE_TO_TARGET,
            )

        create_call.assert_not_called()
        self.assertEqual(stats["skipped"], 1)

    def test_sync_direction_rolls_back_on_issue_error(self):
        from app.services.sync_service import SyncService
        from app.models.sync_log import SyncDirection

        db = _FakeSession(first_queue=[None])
        svc = SyncService(db)

        source_issue = SimpleNamespace(
            iid=1,
            id=100,
            project_id="sproj",
            title="A",
            description="B",
            labels=[],
            assignees=[],
            milestone=None,
            due_date=None,
            state="opened",
            updated_at="2025-01-01T00:00:00Z",
        )

        class _SourceClient:
            def get_issues(self, project_id, updated_after=None):
                return [source_issue]

        class _TargetClient:
            pass

        with patch.object(svc, "_create_issue_from_source", side_effect=RuntimeError("boom"), autospec=True), \
             patch.object(svc, "_log_sync", autospec=True):
            stats = svc._sync_direction(
                project_pair=SimpleNamespace(id=1),
                source_client=_SourceClient(),
                target_client=_TargetClient(),
                source_project_id="sproj",
                target_project_id="tproj",
                source_instance=SimpleNamespace(id=10, url="https://src"),
                target_instance=SimpleNamespace(id=20, url="https://tgt"),
                direction=SyncDirection.SOURCE_TO_TARGET,
            )

        self.assertEqual(stats["errors"], 1)
        self.assertEqual(db.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
