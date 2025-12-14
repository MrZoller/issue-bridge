import unittest


class IssueDescriptionIdempotencyTests(unittest.TestCase):
    def test_add_sync_reference_is_idempotent_with_marker(self):
        from app.services.sync_service import SyncService

        svc = SyncService(db=object())

        desc = "hello" + "\n" + SyncService._issue_marker(
            source_instance_url="https://src",
            source_project_id="p",
            source_issue_iid=1,
        )

        out = svc._add_sync_reference(desc, "https://other", 999, source_project_id="other")
        self.assertEqual(out, desc)

    def test_add_sync_reference_does_not_duplicate_human_line(self):
        from app.services.sync_service import SyncService

        svc = SyncService(db=object())
        desc = "X\n\n---\n*Synced from: https://src/-/issues/1*"

        out = svc._add_sync_reference(desc, "https://src", 1, source_project_id="p")

        # Still only one human-readable line, but marker appended.
        self.assertEqual(out.count("*Synced from:"), 1)
        self.assertIn("gl-issue-sync", out)


if __name__ == "__main__":
    unittest.main()
