"""GitLab API client wrapper"""
import gitlab
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class GitLabClient:
    """Wrapper for GitLab API operations"""

    def __init__(self, url: str, access_token: str):
        """Initialize GitLab client"""
        self.url = url
        self.gl = gitlab.Gitlab(url, private_token=access_token)
        self.gl.auth()

    def get_project(self, project_id: str):
        """Get project by ID or path"""
        try:
            return self.gl.projects.get(project_id)
        except gitlab.exceptions.GitlabGetError as e:
            logger.error(f"Failed to get project {project_id}: {e}")
            raise

    def get_issues(self, project_id: str, updated_after: Optional[datetime] = None) -> List[Any]:
        """Get all issues from a project"""
        try:
            project = self.get_project(project_id)
            # Important defaults:
            # - GitLab defaults to state=opened; we must include closed issues for correct syncing.
            # - Use get_all=True for proper pagination across python-gitlab versions.
            params = {"order_by": "updated_at", "sort": "desc", "state": "all", "per_page": 100}
            if updated_after:
                params["updated_after"] = updated_after.isoformat()

            issues = project.issues.list(get_all=True, **params)
            return issues
        except Exception as e:
            logger.error(f"Failed to get issues for project {project_id}: {e}")
            raise

    def get_issue(self, project_id: str, issue_iid: int) -> Any:
        """Get a specific issue by IID"""
        try:
            project = self.get_project(project_id)
            return project.issues.get(issue_iid)
        except gitlab.exceptions.GitlabGetError as e:
            logger.error(f"Failed to get issue {issue_iid} from project {project_id}: {e}")
            raise

    def get_issue_or_none(self, project_id: str, issue_iid: int) -> Optional[Any]:
        """Get a specific issue by IID, returning None on 404."""
        try:
            return self.get_issue(project_id, issue_iid)
        except gitlab.exceptions.GitlabGetError as e:
            if getattr(e, "response_code", None) == 404:
                return None
            raise

    def create_issue(self, project_id: str, issue_data: Dict[str, Any]) -> Any:
        """Create a new issue"""
        try:
            project = self.get_project(project_id)
            issue = project.issues.create(issue_data)
            logger.info(f"Created issue #{issue.iid} in project {project_id}")
            return issue
        except Exception as e:
            logger.error(f"Failed to create issue in project {project_id}: {e}")
            raise

    def update_issue(self, project_id: str, issue_iid: int, issue_data: Dict[str, Any]) -> Any:
        """Update an existing issue"""
        try:
            project = self.get_project(project_id)
            issue = project.issues.get(issue_iid)
            for key, value in issue_data.items():
                setattr(issue, key, value)
            issue.save()
            logger.info(f"Updated issue #{issue_iid} in project {project_id}")
            return issue
        except Exception as e:
            logger.error(f"Failed to update issue {issue_iid} in project {project_id}: {e}")
            raise

    def get_issue_notes(self, project_id: str, issue_iid: int) -> List[Any]:
        """Get all notes (comments) for an issue"""
        try:
            project = self.get_project(project_id)
            issue = project.issues.get(issue_iid)
            return issue.notes.list(all=True, order_by="created_at", sort="asc")
        except Exception as e:
            logger.error(f"Failed to get notes for issue {issue_iid}: {e}")
            raise

    def create_issue_note(self, project_id: str, issue_iid: int, note_body: str) -> Any:
        """Create a note (comment) on an issue"""
        try:
            project = self.get_project(project_id)
            issue = project.issues.get(issue_iid)
            note = issue.notes.create({"body": note_body})
            logger.info(f"Created note on issue #{issue_iid}")
            return note
        except Exception as e:
            logger.error(f"Failed to create note on issue {issue_iid}: {e}")
            raise

    def get_user_by_username(self, username: str) -> Optional[Any]:
        """Get user by username"""
        try:
            users = self.gl.users.list(username=username)
            return users[0] if users else None
        except Exception as e:
            logger.error(f"Failed to get user {username}: {e}")
            return None

    def get_project_labels(self, project_id: str) -> List[Any]:
        """Get all labels for a project"""
        try:
            project = self.get_project(project_id)
            return project.labels.list(all=True)
        except Exception as e:
            logger.error(f"Failed to get labels for project {project_id}: {e}")
            raise

    def create_label(self, project_id: str, name: str, color: str = "#428BCA") -> Any:
        """Create a label in a project"""
        try:
            project = self.get_project(project_id)
            label = project.labels.create({"name": name, "color": color})
            logger.info(f"Created label '{name}' in project {project_id}")
            return label
        except Exception as e:
            logger.warning(f"Failed to create label '{name}': {e}")
            return None

    def get_project_milestones(self, project_id: str) -> List[Any]:
        """Get all milestones for a project"""
        try:
            project = self.get_project(project_id)
            return project.milestones.list(all=True)
        except Exception as e:
            logger.error(f"Failed to get milestones for project {project_id}: {e}")
            raise

    def create_milestone(self, project_id: str, milestone_data: Dict[str, Any]) -> Any:
        """Create a milestone in a project"""
        try:
            project = self.get_project(project_id)
            milestone = project.milestones.create(milestone_data)
            logger.info(f"Created milestone '{milestone_data.get('title')}' in project {project_id}")
            return milestone
        except Exception as e:
            logger.warning(f"Failed to create milestone: {e}")
            return None
