import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import logging

import gitlab

logging.disable(logging.CRITICAL)


class GitLabClientApiCallTests(unittest.TestCase):
    def test_init_constructs_client_and_auths(self):
        from app.services.gitlab_client import GitLabClient

        with patch("app.services.gitlab_client.gitlab.Gitlab") as gitlab_ctor:
            gl = Mock()
            gitlab_ctor.return_value = gl

            client = GitLabClient("https://gitlab.example", "token")

            self.assertEqual(client.url, "https://gitlab.example")
            gitlab_ctor.assert_called_once_with("https://gitlab.example", private_token="token")
            gl.auth.assert_called_once_with()

    def test_get_project_calls_projects_get(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        client.gl = Mock()
        project = object()
        client.gl.projects.get = Mock(return_value=project)

        self.assertIs(client.get_project("group/proj"), project)
        client.gl.projects.get.assert_called_once_with("group/proj")

    def test_get_project_raises_gitlab_get_error(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        client.gl = Mock()
        client.gl.projects.get = Mock(side_effect=gitlab.exceptions.GitlabGetError("nope", 404))

        with self.assertRaises(gitlab.exceptions.GitlabGetError):
            client.get_project("missing")

    def test_get_issues_calls_issues_list_with_expected_params(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        project = Mock()
        project.issues.list = Mock(return_value=["i1"])
        client.get_project = Mock(return_value=project)

        updated_after = datetime(2025, 1, 2, tzinfo=timezone.utc)
        issues = client.get_issues("group/proj", updated_after=updated_after)

        self.assertEqual(issues, ["i1"])
        client.get_project.assert_called_once_with("group/proj")
        project.issues.list.assert_called_once()

        _, kwargs = project.issues.list.call_args
        # python-gitlab pagination flag
        self.assertTrue(kwargs["get_all"])
        self.assertEqual(kwargs["state"], "all")
        self.assertEqual(kwargs["per_page"], 100)
        self.assertTrue(kwargs["with_time_stats"])
        self.assertEqual(kwargs["order_by"], "updated_at")
        self.assertEqual(kwargs["sort"], "desc")
        self.assertEqual(kwargs["updated_after"], updated_after.isoformat())

    def test_get_issues_without_updated_after_does_not_send_param(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        project = Mock()
        project.issues.list = Mock(return_value=["i1"])
        client.get_project = Mock(return_value=project)

        _ = client.get_issues("group/proj", updated_after=None)

        _, kwargs = project.issues.list.call_args
        self.assertNotIn("updated_after", kwargs)

    def test_get_issue_calls_issues_get(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        project = Mock()
        project.issues.get = Mock(return_value="issue")
        client.get_project = Mock(return_value=project)

        self.assertEqual(client.get_issue("proj", 12), "issue")
        client.get_project.assert_called_once_with("proj")
        project.issues.get.assert_called_once_with(12)

    def test_get_issue_or_none_returns_none_on_404(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        client.get_issue = Mock(side_effect=gitlab.exceptions.GitlabGetError("nope", 404))

        self.assertIsNone(client.get_issue_or_none("proj", 1))

    def test_get_issue_or_none_raises_on_non_404(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        client.get_issue = Mock(side_effect=gitlab.exceptions.GitlabGetError("nope", 500))

        with self.assertRaises(gitlab.exceptions.GitlabGetError):
            client.get_issue_or_none("proj", 1)

    def test_create_issue_calls_issues_create(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        created = Mock(iid=3)
        project = Mock()
        project.issues.create = Mock(return_value=created)
        client.get_project = Mock(return_value=project)

        payload = {"title": "T"}
        out = client.create_issue("proj", payload)

        self.assertIs(out, created)
        project.issues.create.assert_called_once_with(payload)

    def test_update_issue_sets_fields_and_saves(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        issue = Mock()
        issue.save = Mock()
        project = Mock()
        project.issues.get = Mock(return_value=issue)
        client.get_project = Mock(return_value=project)

        out = client.update_issue("proj", 9, {"title": "New", "labels": ["a"]})

        self.assertIs(out, issue)
        self.assertEqual(issue.title, "New")
        self.assertEqual(issue.labels, "a")
        issue.save.assert_called_once_with()

    def test_get_issue_notes_calls_notes_list(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        notes = Mock()
        notes.list = Mock(return_value=["n"])
        issue = Mock()
        issue.notes = notes
        project = Mock()
        project.issues.get = Mock(return_value=issue)
        client.get_project = Mock(return_value=project)

        out = client.get_issue_notes("proj", 5)

        self.assertEqual(out, ["n"])
        project.issues.get.assert_called_once_with(5)
        notes.list.assert_called_once_with(get_all=True, per_page=100, order_by="created_at", sort="asc")

    def test_create_issue_note_calls_notes_create(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        notes = Mock()
        notes.create = Mock(return_value="note")
        issue = Mock()
        issue.notes = notes
        project = Mock()
        project.issues.get = Mock(return_value=issue)
        client.get_project = Mock(return_value=project)

        out = client.create_issue_note("proj", 5, "hello")

        self.assertEqual(out, "note")
        notes.create.assert_called_once_with({"body": "hello"})

    def test_get_user_by_username_returns_first_or_none(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        client.gl = Mock()
        client.gl.users.list = Mock(return_value=["u1", "u2"])

        self.assertEqual(client.get_user_by_username("alice"), "u1")
        client.gl.users.list.assert_called_once_with(username="alice")

        client.gl.users.list = Mock(return_value=[])
        self.assertIsNone(client.get_user_by_username("nobody"))

    def test_get_user_by_username_returns_none_on_exception(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        client.gl = Mock()
        client.gl.users.list = Mock(side_effect=RuntimeError("boom"))

        self.assertIsNone(client.get_user_by_username("alice"))

    def test_get_project_labels_calls_labels_list(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        project = Mock()
        project.labels.list = Mock(return_value=["l"])
        client.get_project = Mock(return_value=project)

        out = client.get_project_labels("proj")

        self.assertEqual(out, ["l"])
        project.labels.list.assert_called_once_with(get_all=True, per_page=100)

    def test_create_label_returns_label_or_none_on_error(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        project = Mock()
        project.labels.create = Mock(return_value="label")
        client.get_project = Mock(return_value=project)

        self.assertEqual(client.create_label("proj", "bug"), "label")
        project.labels.create.assert_called_once_with({"name": "bug", "color": "#428BCA"})

        project.labels.create = Mock(side_effect=RuntimeError("fail"))
        self.assertIsNone(client.create_label("proj", "bug"))

    def test_get_project_milestones_calls_milestones_list(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        project = Mock()
        project.milestones.list = Mock(return_value=["m"])
        client.get_project = Mock(return_value=project)

        out = client.get_project_milestones("proj")

        self.assertEqual(out, ["m"])
        project.milestones.list.assert_called_once_with(get_all=True, per_page=100)

    def test_update_issue_normalizes_empty_labels_and_due_date(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        issue = Mock()
        issue.save = Mock()
        project = Mock()
        project.issues.get = Mock(return_value=issue)
        client.get_project = Mock(return_value=project)

        client.update_issue("proj", 9, {"labels": [], "due_date": None})

        self.assertEqual(issue.labels, "")
        self.assertEqual(issue.due_date, "")
        issue.save.assert_called_once_with()

    def test_create_milestone_returns_milestone_or_none_on_error(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        project = Mock()
        project.milestones.create = Mock(return_value="ms")
        client.get_project = Mock(return_value=project)

        out = client.create_milestone("proj", {"title": "v1"})
        self.assertEqual(out, "ms")
        project.milestones.create.assert_called_once_with({"title": "v1"})

        project.milestones.create = Mock(side_effect=RuntimeError("fail"))
        self.assertIsNone(client.create_milestone("proj", {"title": "v2"}))

    def test_set_and_reset_issue_time_estimate_calls_http_post(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        client.gl = Mock()
        client.gl.http_post = Mock(return_value={"ok": True})

        out = client.set_issue_time_estimate("group/proj", 9, 120)
        self.assertEqual(out, {"ok": True})
        client.gl.http_post.assert_called_with(
            "/projects/group%2Fproj/issues/9/time_estimate",
            post_data={"duration": "120s"},
        )

        client.gl.http_post.reset_mock()
        out2 = client.reset_issue_time_estimate("group/proj", 9)
        self.assertEqual(out2, {"ok": True})
        client.gl.http_post.assert_called_with(
            "/projects/group%2Fproj/issues/9/reset_time_estimate",
            post_data={},
        )

    def test_iteration_and_epic_http_endpoints(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        client.gl = Mock()
        client.gl.http_list = Mock(return_value=[{"id": 1}])
        client.gl.http_post = Mock(return_value={"ok": True})

        out = client.list_group_iterations(5)
        self.assertEqual(out, [{"id": 1}])
        client.gl.http_list.assert_called_with("/groups/5/iterations", query_data={"per_page": 100})

        client.gl.http_list.reset_mock()
        out2 = client.list_group_epics(6, search="Epic")
        self.assertEqual(out2, [{"id": 1}])
        client.gl.http_list.assert_called_with("/groups/6/epics", query_data={"per_page": 100, "search": "Epic"})

        client.gl.http_post.reset_mock()
        out3 = client.add_issue_to_epic(6, 12, issue_id=99)
        self.assertEqual(out3, {"ok": True})
        client.gl.http_post.assert_called_with("/groups/6/epics/12/issues/99", post_data={})


if __name__ == "__main__":
    unittest.main()
