import unittest
from datetime import datetime, timezone


class _StubIssues:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return ["ok"]


class _StubProject:
    def __init__(self, issues):
        self.issues = issues


class GitLabClientGetIssuesTests(unittest.TestCase):
    def test_get_issues_requests_state_all_and_pagination(self):
        # Import inside test so unittest discovery doesn't fail if deps are missing
        from app.services.gitlab_client import GitLabClient

        issues = _StubIssues()
        project = _StubProject(issues)

        # Avoid running GitLabClient.__init__ (auth/network); patch get_project.
        client = GitLabClient.__new__(GitLabClient)
        client.get_project = lambda project_id: project

        updated_after = datetime(2025, 1, 1, tzinfo=timezone.utc)
        result = client.get_issues("group/project", updated_after=updated_after)

        self.assertEqual(result, ["ok"])
        self.assertEqual(len(issues.calls), 1)

        params = issues.calls[0]
        self.assertEqual(params["state"], "all")
        self.assertEqual(params["per_page"], 100)
        self.assertEqual(params["order_by"], "updated_at")
        self.assertEqual(params["sort"], "desc")
        # python-gitlab uses get_all for pagination in many versions
        self.assertTrue(params["get_all"])  # type: ignore[truthy-bool]
        self.assertEqual(params["updated_after"], updated_after.isoformat())


if __name__ == "__main__":
    unittest.main()
