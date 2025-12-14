"""GitLab API client wrapper"""
import gitlab
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import time
from urllib.parse import quote

logger = logging.getLogger(__name__)


class GitLabClient:
    """Wrapper for GitLab API operations"""

    def __init__(self, url: str, access_token: str):
        """Initialize GitLab client"""
        self.url = url
        self.gl = gitlab.Gitlab(url, private_token=access_token)
        self.gl.auth()

    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        """Best-effort retry predicate for transient GitLab failures."""
        # python-gitlab exceptions often carry an HTTP response code
        rc = getattr(exc, "response_code", None)
        if rc in (429, 500, 502, 503, 504):
            return True
        # If we can't classify, don't retry to avoid hiding real issues.
        return False

    def _with_retries(self, fn, *, max_attempts: int = 3, base_delay_s: float = 0.5):
        """Run callable with small exponential backoff on transient errors."""
        attempt = 1
        while True:
            try:
                return fn()
            except Exception as e:
                if attempt >= max_attempts or not self._should_retry(e):
                    raise
                time.sleep(base_delay_s * (2 ** (attempt - 1)))
                attempt += 1

    @staticmethod
    def _normalize_issue_payload(issue_data: Dict[str, Any], *, for_update: bool) -> Dict[str, Any]:
        """Normalize payload fields for GitLab API quirks."""
        data = dict(issue_data)

        # GitLab API expects comma-separated string for `labels`. Some servers ignore empty lists.
        if "labels" in data:
            labels = data.get("labels")
            if labels is None:
                if for_update:
                    data["labels"] = ""
                else:
                    data.pop("labels", None)
            elif isinstance(labels, list):
                if len(labels) == 0:
                    if for_update:
                        data["labels"] = ""
                    else:
                        data.pop("labels", None)
                else:
                    data["labels"] = ",".join(labels)

        # Clearing due_date is best-effort with empty string (GitLab accepts this commonly).
        if for_update and "due_date" in data and data.get("due_date") is None:
            data["due_date"] = ""

        return data

    def get_project(self, project_id: str):
        """Get project by ID or path"""
        try:
            return self._with_retries(lambda: self.gl.projects.get(project_id))
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
            params = {
                "order_by": "updated_at",
                "sort": "desc",
                "state": "all",
                "per_page": 100,
                # Needed for robust estimate syncing.
                "with_time_stats": True,
            }
            if updated_after:
                # Our DB uses UTC tz-naive; assume UTC if tzinfo is missing.
                if updated_after.tzinfo is None:
                    updated_after = updated_after.replace(tzinfo=timezone.utc)
                params["updated_after"] = updated_after.isoformat()

            issues = self._with_retries(lambda: project.issues.list(get_all=True, **params))
            return issues
        except Exception as e:
            logger.error(f"Failed to get issues for project {project_id}: {e}")
            raise

    def get_issue(self, project_id: str, issue_iid: int) -> Any:
        """Get a specific issue by IID"""
        try:
            project = self.get_project(project_id)
            return self._with_retries(lambda: project.issues.get(issue_iid))
        except gitlab.exceptions.GitlabGetError as e:
            logger.error(f"Failed to get issue {issue_iid} from project {project_id}: {e}")
            raise

    def get_issue_or_none(self, project_id: str, issue_iid: int) -> Optional[Any]:
        """Get a specific issue by IID, returning None on 404/403."""
        issue, rc = self.get_issue_optional(project_id, issue_iid)
        if issue is not None:
            return issue
        if rc in (403, 404):
            return None
        # For unexpected cases, raise to surface the error.
        raise gitlab.exceptions.GitlabGetError("Failed to get issue", response_code=rc)

    def get_issue_optional(self, project_id: str, issue_iid: int) -> tuple[Optional[Any], Optional[int]]:
        """Get issue by IID, returning (issue, response_code_if_error)."""
        try:
            return self.get_issue(project_id, issue_iid), None
        except gitlab.exceptions.GitlabGetError as e:
            return None, getattr(e, "response_code", None)

    def create_issue(self, project_id: str, issue_data: Dict[str, Any]) -> Any:
        """Create a new issue"""
        try:
            project = self.get_project(project_id)
            payload = self._normalize_issue_payload(issue_data, for_update=False)
            issue = self._with_retries(lambda: project.issues.create(payload))
            logger.info(f"Created issue #{issue.iid} in project {project_id}")
            return issue
        except Exception as e:
            logger.error(f"Failed to create issue in project {project_id}: {e}")
            raise

    def update_issue(self, project_id: str, issue_iid: int, issue_data: Dict[str, Any]) -> Any:
        """Update an existing issue"""
        try:
            project = self.get_project(project_id)
            issue = self._with_retries(lambda: project.issues.get(issue_iid))
            payload = self._normalize_issue_payload(issue_data, for_update=True)
            for key, value in payload.items():
                setattr(issue, key, value)
            self._with_retries(lambda: issue.save())
            logger.info(f"Updated issue #{issue_iid} in project {project_id}")
            return issue
        except Exception as e:
            logger.error(f"Failed to update issue {issue_iid} in project {project_id}: {e}")
            raise

    def get_issue_notes(self, project_id: str, issue_iid: int) -> List[Any]:
        """Get all notes (comments) for an issue"""
        try:
            project = self.get_project(project_id)
            issue = self._with_retries(lambda: project.issues.get(issue_iid))
            return self._with_retries(
                lambda: issue.notes.list(get_all=True, per_page=100, order_by="created_at", sort="asc")
            )
        except Exception as e:
            logger.error(f"Failed to get notes for issue {issue_iid}: {e}")
            raise

    def create_issue_note(self, project_id: str, issue_iid: int, note_body: str) -> Any:
        """Create a note (comment) on an issue"""
        try:
            project = self.get_project(project_id)
            issue = self._with_retries(lambda: project.issues.get(issue_iid))
            note = self._with_retries(lambda: issue.notes.create({"body": note_body}))
            logger.info(f"Created note on issue #{issue_iid}")
            return note
        except Exception as e:
            logger.error(f"Failed to create note on issue {issue_iid}: {e}")
            raise

    def get_user_by_username(self, username: str) -> Optional[Any]:
        """Get user by username"""
        try:
            users = self._with_retries(lambda: self.gl.users.list(username=username))
            return users[0] if users else None
        except Exception as e:
            logger.error(f"Failed to get user {username}: {e}")
            return None

    def get_project_labels(self, project_id: str) -> List[Any]:
        """Get all labels for a project"""
        try:
            project = self.get_project(project_id)
            return self._with_retries(lambda: project.labels.list(get_all=True, per_page=100))
        except Exception as e:
            logger.error(f"Failed to get labels for project {project_id}: {e}")
            raise

    def create_label(self, project_id: str, name: str, color: str = "#428BCA") -> Any:
        """Create a label in a project"""
        try:
            project = self.get_project(project_id)
            label = self._with_retries(lambda: project.labels.create({"name": name, "color": color}))
            logger.info(f"Created label '{name}' in project {project_id}")
            return label
        except Exception as e:
            logger.warning(f"Failed to create label '{name}': {e}")
            return None

    def get_project_milestones(self, project_id: str) -> List[Any]:
        """Get all milestones for a project"""
        try:
            project = self.get_project(project_id)
            return self._with_retries(lambda: project.milestones.list(get_all=True, per_page=100))
        except Exception as e:
            logger.error(f"Failed to get milestones for project {project_id}: {e}")
            raise

    def create_milestone(self, project_id: str, milestone_data: Dict[str, Any]) -> Any:
        """Create a milestone in a project"""
        try:
            project = self.get_project(project_id)
            milestone = self._with_retries(lambda: project.milestones.create(milestone_data))
            logger.info(f"Created milestone '{milestone_data.get('title')}' in project {project_id}")
            return milestone
        except Exception as e:
            logger.warning(f"Failed to create milestone: {e}")
            return None

    def set_issue_time_estimate(self, project_id: str, issue_iid: int, seconds: int) -> Any:
        """Set time estimate for an issue (seconds)."""
        pid = quote(str(project_id), safe="")
        duration = f"{int(seconds)}s"
        path = f"/projects/{pid}/issues/{int(issue_iid)}/time_estimate"
        return self._with_retries(lambda: self.gl.http_post(path, post_data={"duration": duration}))

    def reset_issue_time_estimate(self, project_id: str, issue_iid: int) -> Any:
        """Reset/clear time estimate for an issue."""
        pid = quote(str(project_id), safe="")
        path = f"/projects/{pid}/issues/{int(issue_iid)}/reset_time_estimate"
        return self._with_retries(lambda: self.gl.http_post(path, post_data={}))
