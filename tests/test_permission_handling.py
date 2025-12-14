import unittest
from unittest.mock import Mock

import gitlab


class PermissionHandlingTests(unittest.TestCase):
    def test_get_issue_or_none_returns_none_on_403(self):
        from app.services.gitlab_client import GitLabClient

        client = GitLabClient.__new__(GitLabClient)
        client.get_issue = Mock(side_effect=gitlab.exceptions.GitlabGetError("nope", 403))

        self.assertIsNone(client.get_issue_or_none("proj", 1))


if __name__ == "__main__":
    unittest.main()
