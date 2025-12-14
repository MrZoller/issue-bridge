import unittest
from types import SimpleNamespace


class SyncIssueFieldsWeightAndEstimateTests(unittest.TestCase):
    def test_create_issue_sends_weight_and_sets_time_estimate(self):
        from app.services.sync_service import SyncService

        svc = SyncService(db=SimpleNamespace())

        source_issue = SimpleNamespace(
            iid=1,
            title="T",
            description="D",
            labels=[],
            assignees=[],
            milestone=None,
            due_date=None,
            state="opened",
            weight=5,
            time_stats={"time_estimate": 3600},
        )

        created_target = SimpleNamespace(iid=9, id=900)

        class _TargetClient:
            def __init__(self):
                self.created_payload = None
                self.estimate_calls = []

            def create_issue(self, project_id, payload):
                self.created_payload = payload
                return created_target

            def set_issue_time_estimate(self, project_id, issue_iid, seconds):
                self.estimate_calls.append((project_id, issue_iid, seconds))

            def update_issue(self, project_id, issue_iid, payload):
                raise AssertionError("not expected")

        target_client = _TargetClient()

        # Avoid label/milestone calls in this focused test
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
        self.assertEqual(target_client.created_payload["weight"], 5)
        self.assertEqual(target_client.estimate_calls, [("tproj", 9, 3600)])

    def test_update_issue_sets_weight_and_resets_time_estimate_when_missing(self):
        from app.services.sync_service import SyncService

        svc = SyncService(db=SimpleNamespace())

        source_issue = SimpleNamespace(
            iid=1,
            title="T",
            description="D",
            labels=[],
            assignees=[],
            milestone=None,
            due_date=None,
            state="opened",
            weight=None,
            time_stats=None,
        )

        class _TargetClient:
            def __init__(self):
                self.updated_payload = None
                self.reset_calls = []

            def get_issue(self, project_id, issue_iid):
                return SimpleNamespace(iid=issue_iid, state="opened")

            def update_issue(self, project_id, issue_iid, payload):
                self.updated_payload = payload

            def reset_issue_time_estimate(self, project_id, issue_iid):
                self.reset_calls.append((project_id, issue_iid))

            def set_issue_time_estimate(self, project_id, issue_iid, seconds):
                raise AssertionError("not expected")

        target_client = _TargetClient()

        svc._ensure_labels = lambda *args, **kwargs: None
        svc._ensure_milestone = lambda *args, **kwargs: None
        svc._sync_comments = lambda *args, **kwargs: None

        svc._update_issue_from_source(
            source_issue=source_issue,
            target_issue_iid=9,
            source_instance=SimpleNamespace(id=1, url="https://src"),
            target_client=target_client,
            target_project_id="tproj",
            target_instance_id=2,
            source_project_id="sproj",
            stats=None,
        )

        self.assertIn("weight", target_client.updated_payload)
        self.assertIsNone(target_client.updated_payload["weight"])
        self.assertEqual(target_client.reset_calls, [("tproj", 9)])


if __name__ == "__main__":
    unittest.main()
