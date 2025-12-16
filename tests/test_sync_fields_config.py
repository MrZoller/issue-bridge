import unittest
from types import SimpleNamespace
from unittest.mock import patch


class SyncFieldsConfigTests(unittest.TestCase):
    def test_sync_fields_disabling_labels_skips_label_updates(self):
        # Patch global settings before constructing SyncService
        from app.services import sync_service as sync_service_module

        old = sync_service_module.settings.sync_fields
        sync_service_module.settings.sync_fields = "title,description"  # labels disabled
        try:
            svc = sync_service_module.SyncService(db=SimpleNamespace())

            source_issue = SimpleNamespace(
                iid=1,
                title="T",
                description="D",
                labels=["bug"],
                assignees=[],
                milestone=None,
                due_date=None,
                state="opened",
            )

            class _TargetClient:
                def __init__(self):
                    self.updated_payload = None

                def get_issue(self, project_id, issue_iid):
                    return SimpleNamespace(iid=issue_iid, state="opened", description="Existing")

                def update_issue(self, project_id, issue_iid, payload):
                    self.updated_payload = payload

            target_client = _TargetClient()

            # If labels were attempted, this would blow up
            svc._ensure_labels = lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("labels should not be synced when disabled")
            )

            with patch.object(svc, "_sync_comments", autospec=True):
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

            self.assertIsNotNone(target_client.updated_payload)
            self.assertNotIn("labels", target_client.updated_payload)
        finally:
            sync_service_module.settings.sync_fields = old

    def test_sync_fields_disabling_comments_skips_comment_sync_on_create(self):
        from app.services import sync_service as sync_service_module

        old = sync_service_module.settings.sync_fields
        sync_service_module.settings.sync_fields = "title,description"  # comments disabled
        try:
            svc = sync_service_module.SyncService(db=SimpleNamespace())

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

            created_target = SimpleNamespace(iid=9, id=900)

            class _TargetClient:
                def create_issue(self, project_id, payload):
                    return created_target

                def update_issue(self, project_id, issue_iid, payload):
                    return None

            target_client = _TargetClient()

            # If comment sync is attempted, fail the test
            svc._sync_comments = lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("comments should not be synced when disabled")
            )

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
        finally:
            sync_service_module.settings.sync_fields = old


if __name__ == "__main__":
    unittest.main()
