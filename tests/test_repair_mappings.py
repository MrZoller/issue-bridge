import unittest
from types import SimpleNamespace
from unittest.mock import patch


class _FakeQuery:
    def __init__(self, session, model):
        self._session = session
        self._model = model

    def filter(self, *args, **kwargs):
        # Very small fake: the session uses queues keyed by model name.
        return self

    def first(self):
        q = self._session._first_queues.get(self._model, [])
        if not q:
            return None
        return q.pop(0)


class _FakeSession:
    def __init__(self):
        self._first_queues = {}
        self.added = []
        self.commits = 0

    def seed_first(self, model, values):
        self._first_queues[model] = list(values)

    def query(self, model):
        return _FakeQuery(self, model)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1


class RepairMappingsTests(unittest.TestCase):
    def test_repair_mappings_creates_missing_rows_from_markers(self):
        from app.services.sync_service import SyncService
        from app.models import ProjectPair, SyncedIssue

        db = _FakeSession()

        # ProjectPair query
        pair = SimpleNamespace(
            id=1,
            source_instance_id=10,
            target_instance_id=20,
            source_project_id="sproj",
            target_project_id="tproj",
            source_instance=SimpleNamespace(url="https://src"),
            target_instance=SimpleNamespace(url="https://tgt"),
        )
        db.seed_first(ProjectPair, [pair])

        svc = SyncService(db)

        # No existing mappings for exact/either-side checks
        db.seed_first(SyncedIssue, [None, None])  # _find_synced_issue_by_pair
        # _find_synced_issue_by_either_side does 2 queries; we return None for both.
        db.seed_first(SyncedIssue, [None, None])

        # Issues with marker on target issue pointing to source
        marker = SyncService._issue_marker(
            source_instance_url="https://src",
            source_project_id="sproj",
            source_issue_iid=7,
        )
        source_issue = SimpleNamespace(iid=7, id=700, title="A", description="B", labels=[], state="opened")
        target_issue = SimpleNamespace(iid=9, id=900, title="A", description="X\n" + marker, labels=[], state="opened")

        class _Client:
            def __init__(self, issues):
                self._issues = issues

            def get_issues(self, project_id, updated_after=None):
                return self._issues

        with patch.object(svc, "_get_client", side_effect=[_Client([source_issue]), _Client([target_issue])], autospec=True), \
             patch.object(svc, "_compute_synced_hash", return_value="hash", autospec=True):
            out = svc.repair_mappings(1)

        self.assertEqual(out["status"], "success")
        self.assertEqual(out["stats"]["created"], 1)
        self.assertEqual(len(db.added), 1)
        created = db.added[0]
        self.assertEqual(created.source_issue_iid, 7)
        self.assertEqual(created.target_issue_iid, 9)


if __name__ == "__main__":
    unittest.main()
