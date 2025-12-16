import unittest
from types import SimpleNamespace
from unittest.mock import patch


class SyncIssueFieldCoverageTests(unittest.TestCase):
    def test_create_issue_creates_missing_milestone_and_sets_core_fields(self):
        """Ensure milestone is created on target when missing and key fields are sent."""
        from app.config import settings
        from app.services.sync_service import SyncService

        class _DB:
            def query(self, _model):
                raise AssertionError("DB should not be queried in this unit test")

        with patch.object(
            settings,
            "sync_fields",
            "title,description,state,labels,assignees,milestone,due_date,weight,time_estimate,issue_type,iteration,epic,comments,confidential",
        ):
            svc = SyncService(_DB())

        source_issue = SimpleNamespace(
            iid=1,
            title="T",
            description="D",
            labels=["bug"],
            milestone=SimpleNamespace(title="M1"),
            due_date="2025-01-01",
            weight=2,
            confidential=True,
            state="opened",
        )

        class _TargetClient:
            def __init__(self):
                self.created_milestones = []
                self.created_labels = []
                self.created_issues = []

            def get_project_milestones(self, project_id):
                return []

            def create_milestone(self, project_id, milestone_data):
                self.created_milestones.append((project_id, dict(milestone_data)))
                return SimpleNamespace(id=55, title=milestone_data.get("title"))

            def get_project_labels(self, project_id):
                return []

            def create_label(self, project_id, name, color="#428BCA"):
                self.created_labels.append((project_id, name))
                return SimpleNamespace(id=1, name=name)

            def create_issue(self, project_id, issue_data):
                self.created_issues.append((project_id, dict(issue_data)))
                return SimpleNamespace(iid=10, id=11)

            def update_issue(self, project_id, issue_iid, issue_data):
                raise AssertionError("update_issue should not be called for opened source")

        target_client = _TargetClient()

        with patch.object(svc, "_sync_comments", autospec=True):
            svc._create_issue_from_source(
                source_issue=source_issue,
                source_instance=SimpleNamespace(id=1, url="https://src"),
                target_client=target_client,
                target_project_id="tproj",
                target_instance_id=2,
                source_project_id="sproj",
            )

        self.assertEqual(len(target_client.created_milestones), 1)
        self.assertEqual(target_client.created_milestones[0][1]["title"], "M1")

        self.assertEqual(len(target_client.created_labels), 1)
        self.assertEqual(target_client.created_labels[0][1], "bug")

        self.assertEqual(len(target_client.created_issues), 1)
        _, payload = target_client.created_issues[0]
        self.assertEqual(payload.get("milestone_id"), 55)
        self.assertEqual(payload.get("due_date"), "2025-01-01")
        self.assertEqual(payload.get("weight"), 2)
        self.assertEqual(payload.get("confidential"), True)
        self.assertEqual(payload.get("labels"), ["bug"])

    def test_create_issue_retries_when_optional_field_rejected(self):
        """If GitLab rejects optional fields (e.g. confidential), retry without them."""
        from app.config import settings
        from app.services.sync_service import SyncService

        class _DB:
            def query(self, _model):
                raise AssertionError("DB should not be queried in this unit test")

        with patch.object(
            settings,
            "sync_fields",
            "title,description,state,labels,assignees,milestone,due_date,weight,time_estimate,issue_type,iteration,epic,comments,confidential",
        ):
            svc = SyncService(_DB())

        source_issue = SimpleNamespace(
            iid=1,
            title="T",
            description="D",
            labels=[],
            milestone=None,
            due_date=None,
            weight=None,
            confidential=True,
            state="opened",
        )

        class _TargetClient:
            def __init__(self):
                self.calls = []

            def get_project_milestones(self, project_id):
                return []

            def get_project_labels(self, project_id):
                return []

            def create_issue(self, project_id, issue_data):
                self.calls.append(dict(issue_data))
                if "confidential" in issue_data:
                    raise Exception("400 Bad Request")
                return SimpleNamespace(iid=10, id=11)

            def update_issue(self, project_id, issue_iid, issue_data):
                raise AssertionError("update_issue should not be called")

        target_client = _TargetClient()

        with patch.object(svc, "_sync_comments", autospec=True):
            svc._create_issue_from_source(
                source_issue=source_issue,
                source_instance=SimpleNamespace(id=1, url="https://src"),
                target_client=target_client,
                target_project_id="tproj",
                target_instance_id=2,
                source_project_id="sproj",
            )

        self.assertGreaterEqual(len(target_client.calls), 2)
        self.assertIn("confidential", target_client.calls[0])
        self.assertNotIn("confidential", target_client.calls[-1])

    def test_create_issue_closes_target_when_source_closed(self):
        from app.config import settings
        from app.services.sync_service import SyncService

        class _DB:
            def query(self, _model):
                raise AssertionError("DB should not be queried in this unit test")

        with patch.object(
            settings,
            "sync_fields",
            "title,description,state,labels,assignees,milestone,due_date,weight,time_estimate,issue_type,iteration,epic,comments",
        ):
            svc = SyncService(_DB())

        source_issue = SimpleNamespace(
            iid=1,
            title="T",
            description="D",
            labels=[],
            milestone=None,
            due_date=None,
            weight=None,
            state="closed",
        )

        class _TargetClient:
            def __init__(self):
                self.updated = []

            def get_project_milestones(self, project_id):
                return []

            def get_project_labels(self, project_id):
                return []

            def create_issue(self, project_id, issue_data):
                return SimpleNamespace(iid=10, id=11)

            def update_issue(self, project_id, issue_iid, issue_data):
                self.updated.append((project_id, issue_iid, dict(issue_data)))

        target_client = _TargetClient()

        with patch.object(svc, "_sync_comments", autospec=True):
            svc._create_issue_from_source(
                source_issue=source_issue,
                source_instance=SimpleNamespace(id=1, url="https://src"),
                target_client=target_client,
                target_project_id="tproj",
                target_instance_id=2,
                source_project_id="sproj",
            )

        self.assertEqual(len(target_client.updated), 1)
        _, _, payload = target_client.updated[0]
        self.assertEqual(payload.get("state_event"), "close")


if __name__ == "__main__":
    unittest.main()
