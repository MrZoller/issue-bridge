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

        # Issues with marker on target issue pointing to source (also includes relationship titles)
        marker = SyncService._issue_marker_with_fields(
            source_instance_url="https://src",
            source_project_id="sproj",
            source_issue_iid=7,
            iteration_title="Sprint 1",
            iteration_start_date="2025-01-01",
            iteration_due_date="2025-01-14",
            epic_title="Epic A",
        )
        source_issue = SimpleNamespace(iid=7, id=700, title="A", description="B", labels=[], state="opened")
        target_issue = SimpleNamespace(iid=9, id=900, title="A", description="X\n" + marker, labels=[], state="opened")

        class _Client:
            def __init__(self, issues):
                self._issues = issues
                self.updated = []
                self.epic_links = []

            def get_issues(self, project_id, updated_after=None):
                return self._issues

            def get_issue_optional(self, project_id, issue_iid):
                # Return issue object with no iteration/epic set so repair will apply them.
                for i in self._issues:
                    if int(i.iid) == int(issue_iid):
                        return i, None
                return None, 404

            def update_issue(self, project_id, issue_iid, payload):
                self.updated.append((project_id, issue_iid, payload))

            def add_issue_to_epic(self, group_id, epic_iid, *, issue_id):
                self.epic_links.append((group_id, epic_iid, issue_id))

            def get_project_namespace(self, project_id):
                return {"id": 55, "kind": "group"}

            def list_group_iterations(self, group_id):
                return [{"id": 777, "title": "Sprint 1"}]

            def list_group_epics(self, group_id, search=None):
                return [{"iid": 12, "title": "Epic A"}]

        source_client = _Client([source_issue])
        target_client = _Client([target_issue])

        with patch.object(svc, "_get_client", side_effect=[source_client, target_client], autospec=True), \
             patch.object(svc, "_compute_synced_hash", return_value="hash", autospec=True):
            out = svc.repair_mappings(1)

        self.assertEqual(out["status"], "success")
        self.assertEqual(out["stats"]["created"], 1)
        self.assertEqual(len(db.added), 1)
        created = db.added[0]
        self.assertEqual(created.source_issue_iid, 7)
        self.assertEqual(created.target_issue_iid, 9)

        # Relationship repair applied to the issue containing the marker (target issue).
        self.assertTrue(any(p[2].get("iteration_id") == 777 for p in target_client.updated))
        self.assertEqual(target_client.epic_links, [(55, 12, 900)])


if __name__ == "__main__":
    unittest.main()
