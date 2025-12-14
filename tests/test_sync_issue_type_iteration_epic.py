import unittest
from types import SimpleNamespace


class SyncIssueTypeIterationEpicTests(unittest.TestCase):
    def test_create_issue_includes_issue_type_iteration_and_epic_link(self):
        from app.services.sync_service import SyncService

        svc = SyncService(db=SimpleNamespace())

        source_issue = SimpleNamespace(
            iid=1,
            id=101,
            title="T",
            description="D",
            labels=[],
            assignees=[],
            milestone=None,
            due_date=None,
            state="opened",
            issue_type="incident",
            iteration={"title": "Sprint 1", "start_date": "2025-01-01", "due_date": "2025-01-14"},
            epic={"title": "Epic A"},
            time_stats={"time_estimate": 0},
        )

        created_target = SimpleNamespace(iid=9, id=900)

        class _TargetClient:
            def __init__(self):
                self.created_payload = None
                self.epic_links = []

            def create_issue(self, project_id, payload):
                self.created_payload = payload
                return created_target

            def update_issue(self, project_id, issue_iid, payload):
                return None

            def set_issue_time_estimate(self, project_id, issue_iid, seconds):
                raise AssertionError("not expected")

            def reset_issue_time_estimate(self, project_id, issue_iid):
                return None

            def add_issue_to_epic(self, group_id, epic_iid, *, issue_id):
                self.epic_links.append((group_id, epic_iid, issue_id))

            def get_project_namespace(self, project_id):
                return {"id": 55, "kind": "group"}

            def list_group_iterations(self, group_id):
                return [{"id": 777, "title": "Sprint 1"}]

            def list_group_epics(self, group_id, search=None):
                return [{"iid": 12, "title": "Epic A"}]

            def create_group_iteration(self, group_id, *, title, start_date, due_date):
                raise AssertionError("not expected")

        target_client = _TargetClient()

        svc._ensure_labels = lambda *args, **kwargs: None
        svc._ensure_milestone = lambda *args, **kwargs: None
        svc._sync_comments = lambda *args, **kwargs: None

        out = svc._create_issue_from_source(
            source_issue=source_issue,
            source_instance=SimpleNamespace(id=1, url="https://src"),
            target_client=target_client,
            target_project_id="tproj",
            target_instance_id=2,
            source_project_id="sproj",
            stats=None,
        )

        self.assertIs(out, created_target)
        self.assertEqual(target_client.created_payload["issue_type"], "incident")
        self.assertEqual(target_client.created_payload["iteration_id"], 777)
        self.assertEqual(target_client.epic_links, [(55, 12, 900)])


if __name__ == "__main__":
    unittest.main()
