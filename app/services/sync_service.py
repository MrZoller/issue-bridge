"""Issue synchronization service"""

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import gitlab
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Conflict,
    GitLabInstance,
    ProjectPair,
    SyncedIssue,
    SyncLog,
    UserMapping,
)
from app.models.sync_log import SyncDirection, SyncStatus
from app.services.gitlab_client import GitLabClient

logger = logging.getLogger(__name__)


class SyncService:
    """Service for synchronizing GitLab issues"""

    def __init__(self, db: Session):
        self.db = db
        self.clients: Dict[int, GitLabClient] = {}

    @staticmethod
    def _utcnow() -> datetime:
        """UTC 'now' as tz-naive datetime for DB + comparisons."""
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _normalize_utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
        """Normalize a datetime to UTC tz-naive (safe for comparisons)."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    @classmethod
    def _parse_gitlab_datetime(cls, value: str) -> datetime:
        """Parse GitLab ISO8601 timestamps into UTC tz-naive datetimes."""
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return cls._normalize_utc_naive(dt)

    _SYNC_REF_RE = re.compile(
        r"\*Synced from:\s*(?P<url>https?://[^\s*]+?)/-?/issues/(?P<iid>\d+)\*",
        re.IGNORECASE,
    )
    _ISSUE_MARKER_RE = re.compile(
        r"<!--\s*gl-issue-sync:(?P<b64>[A-Za-z0-9+/=]+)\s*-->",
        re.IGNORECASE,
    )
    _NOTE_MARKER_RE = re.compile(
        r"<!--\s*gl-issue-sync-note:(?P<b64>[A-Za-z0-9+/=]+)\s*-->",
        re.IGNORECASE,
    )

    @staticmethod
    def _normalize_instance_url(url: str) -> str:
        return (url or "").rstrip("/")

    @staticmethod
    def _b64_json(data: Dict[str, Any]) -> str:
        import base64

        raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    @staticmethod
    def _b64_json_load(value: str) -> Optional[Dict[str, Any]]:
        import base64

        try:
            raw = base64.b64decode(value.encode("ascii"))
            obj = json.loads(raw.decode("utf-8"))
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    @classmethod
    def _issue_marker(
        cls, *, source_instance_url: str, source_project_id: str, source_issue_iid: int
    ) -> str:
        payload = {
            "v": 1,
            "source_instance_url": cls._normalize_instance_url(source_instance_url),
            "source_project_id": str(source_project_id),
            "source_issue_iid": int(source_issue_iid),
        }
        return f"<!-- gl-issue-sync:{cls._b64_json(payload)} -->"

    @classmethod
    def _issue_marker_with_fields(
        cls,
        *,
        source_instance_url: str,
        source_project_id: str,
        source_issue_iid: int,
        issue_type: Optional[str] = None,
        milestone_title: Optional[str] = None,
        iteration_title: Optional[str] = None,
        iteration_start_date: Optional[str] = None,
        iteration_due_date: Optional[str] = None,
        epic_title: Optional[str] = None,
    ) -> str:
        payload = {
            "v": 2,
            "source_instance_url": cls._normalize_instance_url(source_instance_url),
            "source_project_id": str(source_project_id),
            "source_issue_iid": int(source_issue_iid),
        }
        if issue_type:
            payload["issue_type"] = str(issue_type)
        if milestone_title:
            payload["milestone_title"] = str(milestone_title)
        if iteration_title:
            payload["iteration_title"] = str(iteration_title)
        if iteration_start_date:
            payload["iteration_start_date"] = str(iteration_start_date)
        if iteration_due_date:
            payload["iteration_due_date"] = str(iteration_due_date)
        if epic_title:
            payload["epic_title"] = str(epic_title)
        return f"<!-- gl-issue-sync:{cls._b64_json(payload)} -->"

    @classmethod
    def _note_marker(
        cls,
        *,
        source_instance_url: str,
        source_project_id: str,
        source_issue_iid: int,
        source_note_id: int,
    ) -> str:
        payload = {
            "v": 1,
            "source_instance_url": cls._normalize_instance_url(source_instance_url),
            "source_project_id": str(source_project_id),
            "source_issue_iid": int(source_issue_iid),
            "source_note_id": int(source_note_id),
        }
        return f"<!-- gl-issue-sync-note:{cls._b64_json(payload)} -->"

    @classmethod
    @classmethod
    def _parse_issue_marker_payload(cls, description: Optional[str]) -> Optional[Dict[str, Any]]:
        if not description:
            return None
        m = cls._ISSUE_MARKER_RE.search(description)
        if not m:
            return None
        return cls._b64_json_load(m.group("b64"))

    @classmethod
    def _parse_issue_marker(cls, description: Optional[str]) -> Optional[Tuple[str, str, int]]:
        """Return (source_instance_url, source_project_id, source_issue_iid) if marker found."""
        data = cls._parse_issue_marker_payload(description)
        if not data:
            return None
        try:
            return (
                cls._normalize_instance_url(str(data["source_instance_url"])),
                str(data["source_project_id"]),
                int(data["source_issue_iid"]),
            )
        except Exception:
            return None

    @classmethod
    def _extract_note_marker(cls, body: Optional[str]) -> Optional[Dict[str, Any]]:
        if not body:
            return None
        m = cls._NOTE_MARKER_RE.search(body)
        if not m:
            return None
        data = cls._b64_json_load(m.group("b64"))
        # Marker present but payload unreadable: still treat as "sync note".
        return data or {}

    @classmethod
    def _parse_sync_reference(cls, description: Optional[str]) -> Optional[Tuple[str, int]]:
        """Parse our sync reference note to detect mirrored issues."""
        if not description:
            return None
        # Prefer machine-readable marker (new format)
        marked = cls._parse_issue_marker(description)
        if marked is not None:
            src_url, _src_pid, src_iid = marked
            return src_url, src_iid
        m = cls._SYNC_REF_RE.search(description)
        if not m:
            return None
        try:
            return cls._normalize_instance_url(m.group("url")), int(m.group("iid"))
        except Exception:
            return None

    @staticmethod
    def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
        """Get attribute or dict key safely."""
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    @classmethod
    def _extract_username(cls, user: Any) -> Optional[str]:
        """Extract username from a GitLab user-ish object (dict or resource)."""
        return cls._safe_attr(user, "username")

    @classmethod
    def _extract_milestone_title(cls, milestone: Any) -> Optional[str]:
        """Extract milestone title from dict or resource."""
        return cls._safe_attr(milestone, "title")

    def _get_client(self, instance_id: int) -> GitLabClient:
        """Get or create GitLab client for instance"""
        if instance_id not in self.clients:
            instance = (
                self.db.query(GitLabInstance).filter(GitLabInstance.id == instance_id).first()
            )
            if not instance:
                raise ValueError(f"GitLab instance {instance_id} not found")
            self.clients[instance_id] = GitLabClient(instance.url, instance.access_token)
        return self.clients[instance_id]

    def _get_user_mapping(
        self, username: str, source_instance_id: int, target_instance_id: int
    ) -> Optional[str]:
        """Get mapped username for target instance.

        Mappings are stored directionally as (source_instance, source_username) -> (target_instance, target_username).
        For bidirectional sync runs we support a reverse lookup so users don't have to enter duplicate mappings.
        """
        mapping = (
            self.db.query(UserMapping)
            .filter(
                UserMapping.source_instance_id == source_instance_id,
                UserMapping.source_username == username,
                UserMapping.target_instance_id == target_instance_id,
            )
            .first()
        )
        if mapping:
            return mapping.target_username

        # Reverse lookup: if someone configured A:user -> B:user2, then when syncing B->A,
        # allow mapping B:user2 -> A:user without requiring a second DB row.
        reverse = (
            self.db.query(UserMapping)
            .filter(
                UserMapping.source_instance_id == target_instance_id,
                UserMapping.target_instance_id == source_instance_id,
                UserMapping.target_username == username,
            )
            .first()
        )
        return reverse.source_username if reverse else None

    def _map_usernames(
        self,
        usernames: List[str],
        source_instance_id: int,
        target_instance_id: int,
        *,
        fallback_username: Optional[str] = None,
    ) -> List[str]:
        """Map list of usernames to target instance.

        If no explicit mapping exists for a username, and `fallback_username` is set,
        use it as a catch-all. If `fallback_username` is not set, the username is
        ignored (current behavior).
        """
        mapped = []
        for username in usernames:
            mapped_username = self._get_user_mapping(
                username, source_instance_id, target_instance_id
            )
            if mapped_username:
                mapped.append(mapped_username)
            else:
                if fallback_username:
                    mapped.append(fallback_username)
                else:
                    logger.warning(f"No mapping found for user '{username}'")
        return mapped

    def _ensure_labels(self, client: GitLabClient, project_id: str, labels: List[str]):
        """Ensure labels exist in target project"""
        existing_labels = {label.name for label in client.get_project_labels(project_id)}
        for label in labels:
            if label not in existing_labels:
                client.create_label(project_id, label)

    def _ensure_milestone(
        self, client: GitLabClient, project_id: str, milestone_title: str
    ) -> Optional[str]:
        """Ensure milestone exists in target project"""
        if not milestone_title:
            return None

        milestones = client.get_project_milestones(project_id)
        for milestone in milestones:
            if milestone.title == milestone_title:
                return milestone.id

        # Create milestone if it doesn't exist
        milestone = client.create_milestone(project_id, {"title": milestone_title})
        return milestone.id if milestone else None

    def _compute_issue_hash(self, issue: Any) -> str:
        """Compute hash of issue content for change detection"""

        def _time_estimate_seconds(obj: Any) -> Optional[int]:
            ts = getattr(obj, "time_stats", None)
            if ts is None:
                return None
            if isinstance(ts, dict):
                val = ts.get("time_estimate")
            else:
                val = getattr(ts, "time_estimate", None)
            if val in (None, "", 0):
                return None
            try:
                return int(val)
            except Exception:
                return None

        assignees = []
        try:
            for a in getattr(issue, "assignees", []) or []:
                u = self._extract_username(a)
                if u:
                    assignees.append(u)
        except Exception:
            assignees = []

        milestone_title = None
        try:
            milestone_title = self._extract_milestone_title(getattr(issue, "milestone", None))
        except Exception:
            milestone_title = None

        data = {
            "title": issue.title,
            "description": issue.description or "",
            "state": issue.state,
            "labels": sorted(issue.labels or []),
            "assignees": sorted(assignees),
            "due_date": getattr(issue, "due_date", None),
            "milestone": milestone_title,
            "weight": getattr(issue, "weight", None),
            "time_estimate_seconds": _time_estimate_seconds(issue),
            "issue_type": getattr(issue, "issue_type", None),
            "iteration": self._safe_attr(getattr(issue, "iteration", None), "title"),
            "epic": self._safe_attr(getattr(issue, "epic", None), "title")
            or getattr(issue, "epic_iid", None),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def _get_cached_group_id(self, client: GitLabClient, project_id: str) -> Optional[int]:
        if not hasattr(self, "_project_group_cache"):
            self._project_group_cache = {}
        cache: Dict[tuple[int, str], Optional[int]] = getattr(self, "_project_group_cache")
        key = (id(client), str(project_id))
        if key in cache:
            return cache[key]
        ns = client.get_project_namespace(project_id)
        gid: Optional[int] = None
        try:
            if ns and str(ns.get("kind", "")).lower() == "group" and ns.get("id") is not None:
                gid = int(ns["id"])
        except Exception:
            gid = None
        cache[key] = gid
        return gid

    def _extract_iteration(self, issue: Any) -> Optional[Dict[str, Any]]:
        it = getattr(issue, "iteration", None)
        if not it:
            return None
        if isinstance(it, dict):
            return it
        # resource-like
        return {
            "id": getattr(it, "id", None),
            "title": getattr(it, "title", None),
            "start_date": getattr(it, "start_date", None),
            "due_date": getattr(it, "due_date", None),
        }

    def _extract_epic(self, issue: Any) -> Optional[Dict[str, Any]]:
        epic = getattr(issue, "epic", None)
        if epic:
            if isinstance(epic, dict):
                return epic
            return {
                "id": getattr(epic, "id", None),
                "iid": getattr(epic, "iid", None),
                "title": getattr(epic, "title", None),
            }
        epic_iid = getattr(issue, "epic_iid", None)
        if epic_iid:
            return {"iid": epic_iid}
        return None

    def _map_iteration_id(
        self, target_client: GitLabClient, target_project_id: str, source_iteration: Dict[str, Any]
    ) -> Optional[int]:
        title = source_iteration.get("title")
        if not title:
            return None
        group_id = self._get_cached_group_id(target_client, target_project_id)
        if not group_id:
            return None
        try:
            iterations = target_client.list_group_iterations(group_id)
        except Exception as e:
            logger.warning(f"Failed to list iterations for group {group_id}: {e}")
            return None
        for it in iterations:
            if str(it.get("title", "")).strip() == str(title).strip():
                try:
                    return int(it["id"])
                except Exception:
                    return None
        # Best-effort create if dates provided
        start_date = source_iteration.get("start_date")
        due_date = source_iteration.get("due_date")
        if start_date and due_date:
            created = target_client.create_group_iteration(
                group_id, title=str(title), start_date=str(start_date), due_date=str(due_date)
            )
            if created and created.get("id") is not None:
                try:
                    return int(created["id"])
                except Exception:
                    return None
        return None

    def _map_epic_iid(
        self, target_client: GitLabClient, target_project_id: str, source_epic: Dict[str, Any]
    ) -> Optional[int]:
        # Prefer title-based mapping (IIDs differ across instances).
        title = source_epic.get("title")
        if not title:
            return None
        group_id = self._get_cached_group_id(target_client, target_project_id)
        if not group_id:
            return None
        try:
            epics = target_client.list_group_epics(group_id, search=str(title))
        except Exception as e:
            logger.warning(f"Failed to list epics for group {group_id}: {e}")
            return None
        # choose exact title match if possible
        for e in epics:
            if str(e.get("title", "")).strip() == str(title).strip():
                iid = e.get("iid")
                if iid is not None:
                    try:
                        return int(iid)
                    except Exception:
                        return None
        return None

    def _add_sync_reference(
        self,
        description: str,
        instance_url: str,
        issue_iid: int,
        source_project_id: Optional[str] = None,
        marker_fields: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add sync reference to issue description"""
        base = self._normalize_instance_url(instance_url)
        desc = description or ""

        # If an issue marker already exists, don't mutate the description (prevents bidirectional ping-pong).
        if self._ISSUE_MARKER_RE.search(desc):
            return desc

        marker = ""
        if source_project_id:
            if marker_fields:
                marker = "\n" + self._issue_marker_with_fields(
                    source_instance_url=base,
                    source_project_id=str(source_project_id),
                    source_issue_iid=int(issue_iid),
                    issue_type=marker_fields.get("issue_type"),
                    milestone_title=marker_fields.get("milestone_title"),
                    iteration_title=marker_fields.get("iteration_title"),
                    iteration_start_date=marker_fields.get("iteration_start_date"),
                    iteration_due_date=marker_fields.get("iteration_due_date"),
                    epic_title=marker_fields.get("epic_title"),
                )
            else:
                marker = "\n" + self._issue_marker(
                    source_instance_url=base,
                    source_project_id=str(source_project_id),
                    source_issue_iid=int(issue_iid),
                )

        # If we already have the human-readable sync reference, just append the marker once (if any).
        if self._SYNC_REF_RE.search(desc):
            if marker and marker not in desc:
                return desc + marker
            return desc

        sync_note = f"\n\n---\n*Synced from: {base}/-/issues/{issue_iid}*{marker}"
        if sync_note not in desc:
            return desc + sync_note
        return desc

    def _compute_synced_hash(
        self, source_issue: Any, *, source_instance_url: str, source_project_id: str
    ) -> str:
        """Compute hash for the content we will actually write to the target."""
        marker_fields = self._marker_fields_from_issue(source_issue)
        synced_description = self._add_sync_reference(
            getattr(source_issue, "description", None) or "",
            source_instance_url,
            int(source_issue.iid),
            source_project_id,
            marker_fields=marker_fields,
        )
        proxy = SimpleNamespace(
            title=getattr(source_issue, "title", ""),
            description=synced_description,
            state=getattr(source_issue, "state", "opened"),
            labels=getattr(source_issue, "labels", []) or [],
            assignees=getattr(source_issue, "assignees", []) or [],
            milestone=getattr(source_issue, "milestone", None),
            due_date=getattr(source_issue, "due_date", None),
            weight=getattr(source_issue, "weight", None),
            time_stats=getattr(source_issue, "time_stats", None),
            updated_at=getattr(source_issue, "updated_at", None),
        )
        return self._compute_issue_hash(proxy)

    def _marker_fields_from_issue(self, issue: Any) -> Dict[str, Any]:
        """Extract stable, title-based fields to persist in markers."""
        milestone_title = None
        try:
            milestone_title = self._extract_milestone_title(getattr(issue, "milestone", None))
        except Exception:
            milestone_title = None

        iteration = self._extract_iteration(issue)
        epic = self._extract_epic(issue)

        fields: Dict[str, Any] = {}
        issue_type = getattr(issue, "issue_type", None)
        if issue_type:
            fields["issue_type"] = issue_type
        if milestone_title:
            fields["milestone_title"] = milestone_title
        if iteration and iteration.get("title"):
            fields["iteration_title"] = iteration.get("title")
            if iteration.get("start_date"):
                fields["iteration_start_date"] = iteration.get("start_date")
            if iteration.get("due_date"):
                fields["iteration_due_date"] = iteration.get("due_date")
        if epic and epic.get("title"):
            fields["epic_title"] = epic.get("title")
        return fields

    def _create_issue_from_source(
        self,
        source_issue: Any,
        source_instance: GitLabInstance,
        target_client: GitLabClient,
        target_project_id: str,
        target_instance_id: int,
        source_project_id: str,
        target_catch_all_username: Optional[str] = None,
        stats: Optional[Dict[str, int]] = None,
    ) -> Any:
        """Create a new issue in target from source issue"""

        def _time_estimate_seconds(obj: Any) -> Optional[int]:
            ts = getattr(obj, "time_stats", None)
            if ts is None:
                return None
            if isinstance(ts, dict):
                val = ts.get("time_estimate")
            else:
                val = getattr(ts, "time_estimate", None)
            if val in (None, "", 0):
                return None
            try:
                return int(val)
            except Exception:
                return None

        # Map assignees
        assignee_ids = []
        if hasattr(source_issue, "assignees") and source_issue.assignees:
            assignee_usernames = [
                u for u in (self._extract_username(a) for a in source_issue.assignees) if u
            ]
            mapped_usernames = self._map_usernames(
                assignee_usernames,
                source_instance.id,
                target_instance_id,
                fallback_username=(target_catch_all_username or None),
            )
            for username in mapped_usernames:
                user = target_client.get_user_by_username(username)
                if user:
                    assignee_ids.append(user.id)

        # Ensure labels exist
        if source_issue.labels:
            self._ensure_labels(target_client, target_project_id, source_issue.labels)

        # Ensure milestone exists
        milestone_id = None
        if hasattr(source_issue, "milestone") and source_issue.milestone:
            milestone_title = self._extract_milestone_title(source_issue.milestone)
            milestone_id = self._ensure_milestone(target_client, target_project_id, milestone_title)

        # Prepare issue data
        synced_description = self._add_sync_reference(
            source_issue.description,
            source_instance.url,
            source_issue.iid,
            source_project_id,
            marker_fields=self._marker_fields_from_issue(source_issue),
        )
        issue_data = {
            "title": source_issue.title,
            "description": synced_description,
            "labels": source_issue.labels if source_issue.labels else [],
        }

        issue_type = getattr(source_issue, "issue_type", None)
        if issue_type:
            issue_data["issue_type"] = issue_type

        if assignee_ids:
            issue_data["assignee_ids"] = assignee_ids

        if milestone_id:
            issue_data["milestone_id"] = milestone_id

        if hasattr(source_issue, "due_date") and source_issue.due_date:
            issue_data["due_date"] = source_issue.due_date

        # Optional fields
        weight = getattr(source_issue, "weight", None)
        if weight is not None:
            issue_data["weight"] = weight

        # Iteration (map by title, best-effort create when possible)
        iteration = self._extract_iteration(source_issue)
        if iteration:
            it_id = self._map_iteration_id(target_client, target_project_id, iteration)
            if it_id:
                issue_data["iteration_id"] = it_id

        # Create issue
        target_issue = target_client.create_issue(target_project_id, issue_data)

        # Time estimate (best-effort via dedicated endpoint)
        estimate_seconds = _time_estimate_seconds(source_issue)
        if estimate_seconds:
            try:
                target_client.set_issue_time_estimate(
                    target_project_id, target_issue.iid, estimate_seconds
                )
            except Exception as e:
                logger.warning(f"Failed to set time estimate on issue #{target_issue.iid}: {e}")

        # Sync comments
        self._sync_comments(
            source_issue,
            target_issue,
            source_instance,
            target_client,
            target_project_id,
            target_instance_id,
            source_project_id,
            stats=stats,
        )

        # Epic link (best-effort, title-mapped)
        epic = self._extract_epic(source_issue)
        if epic and epic.get("title"):
            epic_iid = self._map_epic_iid(target_client, target_project_id, epic)
            group_id = self._get_cached_group_id(target_client, target_project_id)
            if epic_iid and group_id and getattr(target_issue, "id", None):
                try:
                    target_client.add_issue_to_epic(
                        group_id, epic_iid, issue_id=int(target_issue.id)
                    )
                except Exception as e:
                    logger.warning(f"Failed to link epic on created issue #{target_issue.iid}: {e}")

        # Close issue if source is closed
        if source_issue.state == "closed":
            target_client.update_issue(
                target_project_id, target_issue.iid, {"state_event": "close"}
            )

        return target_issue

    def _sync_comments(
        self,
        source_issue: Any,
        target_issue: Any,
        source_instance: GitLabInstance,
        target_client: GitLabClient,
        target_project_id: str,
        target_instance_id: int,
        source_project_id: Optional[str] = None,
        stats: Optional[Dict[str, int]] = None,
    ):
        """Sync comments from source to target issue"""
        try:
            source_client = self._get_client(source_instance.id)
            # Prefer explicit project id/path; fall back to issue.project_id if present.
            source_pid = source_project_id or (
                str(source_issue.project_id) if hasattr(source_issue, "project_id") else None
            )
            if not source_pid:
                raise ValueError("Missing source project id for comment sync")
            try:
                source_notes = source_client.get_issue_notes(source_pid, source_issue.iid)
            except gitlab.exceptions.GitlabGetError as e:
                # Permission/confidential notes shouldn't break issue sync.
                if getattr(e, "response_code", None) in (401, 403):
                    logger.warning(
                        f"Skipping comment sync for source issue #{source_issue.iid} (notes inaccessible)"
                    )
                    if stats is not None:
                        stats["skipped_inaccessible"] = stats.get("skipped_inaccessible", 0) + 1
                        stats["skipped_notes_inaccessible"] = (
                            stats.get("skipped_notes_inaccessible", 0) + 1
                        )
                    return
                raise

            source_base = self._normalize_instance_url(source_instance.url)

            # Get existing target notes to avoid duplicates / loops
            try:
                target_notes = target_client.get_issue_notes(target_project_id, target_issue.iid)
            except gitlab.exceptions.GitlabGetError as e:
                if getattr(e, "response_code", None) in (401, 403):
                    logger.warning(
                        f"Skipping comment sync for target issue #{target_issue.iid} (notes inaccessible)"
                    )
                    if stats is not None:
                        stats["skipped_inaccessible"] = stats.get("skipped_inaccessible", 0) + 1
                        stats["skipped_notes_inaccessible"] = (
                            stats.get("skipped_notes_inaccessible", 0) + 1
                        )
                    return
                raise
            existing_note_markers: set[tuple[str, str, int, int]] = set()
            existing_note_bodies = set()
            for n in target_notes:
                body = getattr(n, "body", None)
                if body:
                    existing_note_bodies.add(body)
                    data = self._extract_note_marker(body)
                    if data:
                        try:
                            existing_note_markers.add(
                                (
                                    self._normalize_instance_url(str(data["source_instance_url"])),
                                    str(data["source_project_id"]),
                                    int(data["source_issue_iid"]),
                                    int(data["source_note_id"]),
                                )
                            )
                        except Exception:
                            pass

            for note in source_notes:
                # Skip system notes
                if note.system:
                    continue
                # Skip notes that were created by this sync tool to prevent ping-pong loops.
                if self._NOTE_MARKER_RE.search(getattr(note, "body", "") or ""):
                    continue

                # Format note with author attribution
                author = self._extract_username(getattr(note, "author", None)) or "unknown"
                source_note_id = getattr(note, "id", None)
                marker = ""
                if source_note_id is not None:
                    marker = "\n\n---\n" + self._note_marker(
                        source_instance_url=source_base,
                        source_project_id=str(source_pid),
                        source_issue_iid=int(source_issue.iid),
                        source_note_id=int(source_note_id),
                    )
                author_note = f"**Comment by @{author}:**\n\n{note.body}{marker}"

                # Skip if already synced
                if author_note in existing_note_bodies:
                    continue
                if source_note_id is not None:
                    key = (source_base, str(source_pid), int(source_issue.iid), int(source_note_id))
                    if key in existing_note_markers:
                        continue

                target_client.create_issue_note(target_project_id, target_issue.iid, author_note)

        except Exception as e:
            logger.error(f"Failed to sync comments: {e}")

    def _find_synced_issue_by_pair(
        self, project_pair_id: int, source_iid: int, target_iid: int
    ) -> Optional[SyncedIssue]:
        return (
            self.db.query(SyncedIssue)
            .filter(
                SyncedIssue.project_pair_id == project_pair_id,
                SyncedIssue.source_issue_iid == source_iid,
                SyncedIssue.target_issue_iid == target_iid,
            )
            .first()
        )

    def _find_synced_issue_by_either_side(
        self, project_pair_id: int, source_iid: int, target_iid: int
    ) -> Optional[SyncedIssue]:
        # Best-effort de-duplication. (We avoid SQLAlchemy `or_` to keep this simple for now.)
        existing = (
            self.db.query(SyncedIssue)
            .filter(
                SyncedIssue.project_pair_id == project_pair_id,
                SyncedIssue.source_issue_iid == source_iid,
            )
            .first()
        )
        if existing:
            return existing
        return (
            self.db.query(SyncedIssue)
            .filter(
                SyncedIssue.project_pair_id == project_pair_id,
                SyncedIssue.target_issue_iid == target_iid,
            )
            .first()
        )

    def repair_mappings(self, project_pair_id: int) -> Dict[str, Any]:
        """
        Rebuild SyncedIssue mappings by scanning issue description markers on both sides.

        Safe by default:
        - Only creates missing mappings.
        - If a conflicting mapping already exists for either side, it is left untouched.
        """
        project_pair = self.db.query(ProjectPair).filter(ProjectPair.id == project_pair_id).first()
        if not project_pair:
            raise ValueError(f"Project pair {project_pair_id} not found")

        source_client = self._get_client(project_pair.source_instance_id)
        target_client = self._get_client(project_pair.target_instance_id)

        source_url = self._normalize_instance_url(project_pair.source_instance.url)
        target_url = self._normalize_instance_url(project_pair.target_instance.url)

        # Full scans; this is a repair job.
        source_issues = source_client.get_issues(project_pair.source_project_id, updated_after=None)
        target_issues = target_client.get_issues(project_pair.target_project_id, updated_after=None)

        source_by_iid = {i.iid: i for i in source_issues}
        target_by_iid = {i.iid: i for i in target_issues}

        pairs: set[tuple[int, int]] = set()
        marker_payloads: Dict[tuple[str, int], Dict[str, Any]] = {}

        # If a SOURCE issue was synced from TARGET, its marker points to TARGET.
        for issue in source_issues:
            payload = self._parse_issue_marker_payload(getattr(issue, "description", None))
            if not payload:
                continue
            marked = self._parse_issue_marker(getattr(issue, "description", None))
            if not marked:
                continue
            m_url, m_pid, m_iid = marked
            if m_url == target_url and m_pid == str(project_pair.target_project_id):
                pairs.add((int(issue.iid), int(m_iid)))
                marker_payloads[("source", int(issue.iid))] = payload

        # If a TARGET issue was synced from SOURCE, its marker points to SOURCE.
        for issue in target_issues:
            payload = self._parse_issue_marker_payload(getattr(issue, "description", None))
            if not payload:
                continue
            marked = self._parse_issue_marker(getattr(issue, "description", None))
            if not marked:
                continue
            m_url, m_pid, m_iid = marked
            if m_url == source_url and m_pid == str(project_pair.source_project_id):
                pairs.add((int(m_iid), int(issue.iid)))
                marker_payloads[("target", int(issue.iid))] = payload

        stats = {
            "created": 0,
            "skipped_existing": 0,
            "conflicts": 0,
            "relationships_applied": 0,
            "relationships_skipped": 0,
            "relationships_failed": 0,
        }

        def _apply_relationships_for_issue(
            client: GitLabClient,
            project_id: str,
            issue_iid: int,
            issue_id: int,
            payload: Dict[str, Any],
        ):
            # Only apply when the marker actually includes any relationship fields.
            if not any(
                k in payload
                for k in ("issue_type", "milestone_title", "iteration_title", "epic_title")
            ):
                stats["relationships_skipped"] += 1
                return

            # Fetch full issue to avoid overwriting existing relationships.
            issue_obj, rc = client.get_issue_optional(project_id, issue_iid)
            if issue_obj is None:
                stats["relationships_skipped"] += 1
                return

            patch_data: Dict[str, Any] = {}

            # issue_type
            if payload.get("issue_type") and not getattr(issue_obj, "issue_type", None):
                patch_data["issue_type"] = payload["issue_type"]

            # milestone
            if payload.get("milestone_title") and not getattr(issue_obj, "milestone", None):
                try:
                    ms_id = self._ensure_milestone(
                        client, project_id, str(payload["milestone_title"])
                    )
                    if ms_id:
                        patch_data["milestone_id"] = ms_id
                except Exception:
                    pass

            # iteration
            if payload.get("iteration_title") and not getattr(issue_obj, "iteration", None):
                it = {
                    "title": payload.get("iteration_title"),
                    "start_date": payload.get("iteration_start_date"),
                    "due_date": payload.get("iteration_due_date"),
                }
                try:
                    it_id = self._map_iteration_id(client, project_id, it)
                    if it_id:
                        patch_data["iteration_id"] = it_id
                except Exception:
                    pass

            if patch_data:
                try:
                    client.update_issue(project_id, issue_iid, patch_data)
                except Exception:
                    stats["relationships_failed"] += 1
                    return

            # epic link
            if payload.get("epic_title") and not getattr(issue_obj, "epic", None) and issue_id:
                try:
                    epic_iid = self._map_epic_iid(
                        client, project_id, {"title": payload.get("epic_title")}
                    )
                    group_id = self._get_cached_group_id(client, project_id)
                    if epic_iid and group_id:
                        client.add_issue_to_epic(group_id, epic_iid, issue_id=int(issue_id))
                except Exception:
                    stats["relationships_failed"] += 1
                    return

            stats["relationships_applied"] += 1

        for source_iid, target_iid in sorted(pairs):
            # Exact match exists
            if self._find_synced_issue_by_pair(project_pair.id, source_iid, target_iid):
                stats["skipped_existing"] += 1
                # Still best-effort repair relationships from markers.
                if ("source", source_iid) in marker_payloads:
                    _apply_relationships_for_issue(
                        source_client,
                        project_pair.source_project_id,
                        source_iid,
                        int(getattr(source_by_iid.get(source_iid), "id", 0) or 0),
                        marker_payloads[("source", source_iid)],
                    )
                if ("target", target_iid) in marker_payloads:
                    _apply_relationships_for_issue(
                        target_client,
                        project_pair.target_project_id,
                        target_iid,
                        int(getattr(target_by_iid.get(target_iid), "id", 0) or 0),
                        marker_payloads[("target", target_iid)],
                    )
                continue

            # Any mapping exists for either side => conflict
            if self._find_synced_issue_by_either_side(project_pair.id, source_iid, target_iid):
                stats["conflicts"] += 1
                continue

            source_issue = source_by_iid.get(source_iid)
            target_issue = target_by_iid.get(target_iid)
            if not source_issue or not target_issue:
                stats["conflicts"] += 1
                continue

            synced_hash = self._compute_synced_hash(
                source_issue,
                source_instance_url=project_pair.source_instance.url,
                source_project_id=project_pair.source_project_id,
            )

            row = SyncedIssue(
                project_pair_id=project_pair.id,
                source_issue_iid=int(source_issue.iid),
                source_issue_id=int(source_issue.id),
                target_issue_iid=int(target_issue.iid),
                target_issue_id=int(target_issue.id),
                sync_hash=synced_hash,
                last_synced_at=self._utcnow(),
            )
            if self._safe_commit_synced_issue(row):
                stats["created"] += 1
            else:
                stats["conflicts"] += 1

            # Best-effort relationship repair after mapping is in place.
            if ("source", source_iid) in marker_payloads:
                _apply_relationships_for_issue(
                    source_client,
                    project_pair.source_project_id,
                    source_iid,
                    int(getattr(source_issue, "id", 0) or 0),
                    marker_payloads[("source", source_iid)],
                )
            if ("target", target_iid) in marker_payloads:
                _apply_relationships_for_issue(
                    target_client,
                    project_pair.target_project_id,
                    target_iid,
                    int(getattr(target_issue, "id", 0) or 0),
                    marker_payloads[("target", target_iid)],
                )

        return {"status": "success", "stats": stats, "pairs_found": len(pairs)}

    def _update_issue_from_source(
        self,
        source_issue: Any,
        target_issue_iid: int,
        source_instance: GitLabInstance,
        target_client: GitLabClient,
        target_project_id: str,
        target_instance_id: int,
        source_project_id: str,
        target_catch_all_username: Optional[str] = None,
        stats: Optional[Dict[str, int]] = None,
    ):
        """Update existing target issue from source"""

        def _time_estimate_seconds(obj: Any) -> Optional[int]:
            ts = getattr(obj, "time_stats", None)
            if ts is None:
                return None
            if isinstance(ts, dict):
                val = ts.get("time_estimate")
            else:
                val = getattr(ts, "time_estimate", None)
            if val in (None, "", 0):
                return None
            try:
                return int(val)
            except Exception:
                return None

        # Map assignees
        # Always set assignee_ids so removals on source clear target.
        assignee_ids: List[int] = []
        if hasattr(source_issue, "assignees") and source_issue.assignees:
            assignee_usernames = [
                u for u in (self._extract_username(a) for a in source_issue.assignees) if u
            ]
            mapped_usernames = self._map_usernames(
                assignee_usernames,
                source_instance.id,
                target_instance_id,
                fallback_username=(target_catch_all_username or None),
            )
            for username in mapped_usernames:
                user = target_client.get_user_by_username(username)
                if user:
                    assignee_ids.append(user.id)

        # Ensure labels exist
        if source_issue.labels:
            self._ensure_labels(target_client, target_project_id, source_issue.labels)

        # Ensure milestone exists
        milestone_id = None
        if hasattr(source_issue, "milestone") and source_issue.milestone:
            milestone_title = self._extract_milestone_title(source_issue.milestone)
            milestone_id = self._ensure_milestone(target_client, target_project_id, milestone_title)

        # Prepare update data
        synced_description = self._add_sync_reference(
            source_issue.description,
            source_instance.url,
            source_issue.iid,
            source_project_id,
            marker_fields=self._marker_fields_from_issue(source_issue),
        )
        update_data = {
            "title": source_issue.title,
            "description": synced_description,
            "labels": source_issue.labels if source_issue.labels else [],
            "assignee_ids": assignee_ids,
        }

        issue_type = getattr(source_issue, "issue_type", None)
        if issue_type:
            update_data["issue_type"] = issue_type

        # Always set milestone_id/due_date so removals clear target.
        # GitLab often uses milestone_id=0 to clear; treat None as "clear".
        update_data["milestone_id"] = milestone_id if milestone_id is not None else 0
        update_data["due_date"] = getattr(source_issue, "due_date", None)
        # Weight can be null on GitLab; set it explicitly so removals clear.
        update_data["weight"] = getattr(source_issue, "weight", None)

        iteration = self._extract_iteration(source_issue)
        if iteration:
            it_id = self._map_iteration_id(target_client, target_project_id, iteration)
            if it_id:
                update_data["iteration_id"] = it_id

        # Handle state changes
        target_issue = target_client.get_issue(target_project_id, target_issue_iid)
        if source_issue.state != target_issue.state:
            update_data["state_event"] = "close" if source_issue.state == "closed" else "reopen"

        # Update issue
        target_client.update_issue(target_project_id, target_issue_iid, update_data)

        # Time estimate (best-effort via dedicated endpoint)
        estimate_seconds = _time_estimate_seconds(source_issue)
        try:
            if estimate_seconds:
                target_client.set_issue_time_estimate(
                    target_project_id, target_issue_iid, estimate_seconds
                )
            else:
                target_client.reset_issue_time_estimate(target_project_id, target_issue_iid)
        except Exception as e:
            logger.warning(f"Failed to sync time estimate for issue #{target_issue_iid}: {e}")

        # Sync new comments
        self._sync_comments(
            source_issue,
            target_issue,
            source_instance,
            target_client,
            target_project_id,
            target_instance_id,
            source_project_id,
            stats=stats,
        )

        # Epic link (best-effort, title-mapped)
        epic = self._extract_epic(source_issue)
        if epic and epic.get("title"):
            epic_iid = self._map_epic_iid(target_client, target_project_id, epic)
            group_id = self._get_cached_group_id(target_client, target_project_id)
            if epic_iid and group_id and getattr(target_issue, "id", None):
                try:
                    target_client.add_issue_to_epic(
                        group_id, epic_iid, issue_id=int(target_issue.id)
                    )
                except Exception as e:
                    logger.warning(f"Failed to link epic on updated issue #{target_issue_iid}: {e}")

    def _detect_conflict(
        self, synced_issue: SyncedIssue, source_issue: Any, target_issue: Any
    ) -> bool:
        """Detect if both issues were updated since last sync"""
        source_updated = self._parse_gitlab_datetime(source_issue.updated_at)
        target_updated = self._parse_gitlab_datetime(target_issue.updated_at)
        last_synced_at = self._normalize_utc_naive(synced_issue.last_synced_at)

        # If both were updated after last sync, we have a conflict
        if last_synced_at:
            if not (source_updated > last_synced_at and target_updated > last_synced_at):
                return False

            # Reduce false positives: updated_at can change due to comments/system notes.
            # If either side's *content* still matches the last synced baseline hash, don't treat it as conflict.
            baseline = getattr(synced_issue, "sync_hash", None)
            if baseline:
                try:
                    if self._compute_issue_hash(source_issue) == baseline:
                        return False
                    if self._compute_issue_hash(target_issue) == baseline:
                        return False
                except Exception:
                    # If hashing fails for any reason, fall back to timestamp-based behavior.
                    pass
            return True
        return False

    def _log_conflict(
        self,
        project_pair: ProjectPair,
        synced_issue: SyncedIssue,
        source_issue: Any,
        target_issue: Any,
        conflict_type: str,
    ):
        """Log a conflict for manual resolution"""
        # `target_issue` may be missing for some conflict types (deleted/not found/etc).
        # Logging a conflict should never break the sync run.
        target_issue_iid = getattr(target_issue, "iid", None)
        if target_issue_iid is None and synced_issue is not None:
            # Best-effort: still record the mapped target IID if we know it.
            target_issue_iid = getattr(synced_issue, "target_issue_iid", None)

        conflict = Conflict(
            project_pair_id=project_pair.id,
            synced_issue_id=synced_issue.id if synced_issue else None,
            source_issue_iid=source_issue.iid,
            target_issue_iid=target_issue_iid,
            conflict_type=conflict_type,
            description=(
                "Concurrent updates detected on both instances"
                if conflict_type == "concurrent_update"
                else f"Conflict detected: {conflict_type}"
            ),
            source_data=json.dumps(
                {
                    "title": source_issue.title,
                    "state": source_issue.state,
                    "updated_at": source_issue.updated_at,
                }
            ),
            target_data=json.dumps(
                {
                    "title": target_issue.title,
                    "state": target_issue.state,
                    "updated_at": target_issue.updated_at,
                }
            )
            if target_issue
            else None,
        )
        try:
            self.db.add(conflict)
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to persist conflict log ({conflict_type}): {e}")
            return

        logger.warning(f"Conflict detected: {conflict_type} for source issue #{source_issue.iid}")

    def _log_sync(
        self,
        project_pair: ProjectPair,
        status: SyncStatus,
        direction: Optional[SyncDirection] = None,
        message: str = "",
        source_iid: Optional[int] = None,
        target_iid: Optional[int] = None,
    ):
        """Log sync operation"""
        log = SyncLog(
            project_pair_id=project_pair.id,
            status=status,
            direction=direction,
            message=message,
            source_issue_iid=source_iid,
            target_issue_iid=target_iid,
        )
        self.db.add(log)
        self.db.commit()

    def _safe_commit_synced_issue(self, row: SyncedIssue) -> bool:
        """Commit a SyncedIssue row, swallowing duplicate-mapping races."""
        try:
            self.db.add(row)
            self.db.commit()
            return True
        except IntegrityError:
            # Another worker likely created the mapping first.
            self.db.rollback()
            return False

    def sync_project_pair(self, project_pair_id: int) -> Dict[str, Any]:
        """Sync issues for a project pair"""
        project_pair = self.db.query(ProjectPair).filter(ProjectPair.id == project_pair_id).first()

        if not project_pair:
            raise ValueError(f"Project pair {project_pair_id} not found")

        if not project_pair.sync_enabled:
            logger.info(f"Sync disabled for project pair {project_pair.name}")
            return {"status": "skipped", "message": "Sync disabled"}

        logger.info(f"Starting sync for project pair: {project_pair.name}")

        source_client = self._get_client(project_pair.source_instance_id)
        target_client = self._get_client(project_pair.target_instance_id)

        stats = {
            "created": 0,
            "updated": 0,
            "conflicts": 0,
            "skipped": 0,
            "skipped_inaccessible": 0,
            "skipped_notes_inaccessible": 0,
            "errors": 0,
        }

        try:
            # Use incremental sync after the first successful run.
            # Add a small overlap to reduce risk of missing updates due to clock skew.
            updated_after = None
            if project_pair.last_sync_at is not None:
                updated_after = self._normalize_utc_naive(project_pair.last_sync_at) - timedelta(
                    minutes=2
                )

            # Sync from source to target
            stats_s2t = self._sync_direction(
                project_pair,
                source_client,
                target_client,
                project_pair.source_project_id,
                project_pair.target_project_id,
                project_pair.source_instance,
                project_pair.target_instance,
                SyncDirection.SOURCE_TO_TARGET,
                updated_after=updated_after,
            )
            for key in stats:
                stats[key] += stats_s2t[key]

            # Sync from target to source if bidirectional
            if project_pair.bidirectional:
                stats_t2s = self._sync_direction(
                    project_pair,
                    target_client,
                    source_client,
                    project_pair.target_project_id,
                    project_pair.source_project_id,
                    project_pair.target_instance,
                    project_pair.source_instance,
                    SyncDirection.TARGET_TO_SOURCE,
                    updated_after=updated_after,
                )
                for key in stats:
                    stats[key] += stats_t2s[key]

            # Update last sync time
            project_pair.last_sync_at = self._utcnow()
            self.db.commit()

            logger.info(f"Sync completed for {project_pair.name}: {stats}")
            self._log_sync(project_pair, SyncStatus.SUCCESS, message=f"Sync completed: {stats}")

            return {"status": "success", "stats": stats}

        except Exception as e:
            logger.error(f"Sync failed for {project_pair.name}: {e}")
            self._log_sync(project_pair, SyncStatus.FAILED, message=f"Sync failed: {str(e)}")
            stats["errors"] += 1
            return {"status": "failed", "error": str(e), "stats": stats}

    def _sync_direction(
        self,
        project_pair: ProjectPair,
        source_client: GitLabClient,
        target_client: GitLabClient,
        source_project_id: str,
        target_project_id: str,
        source_instance: GitLabInstance,
        target_instance: GitLabInstance,
        direction: SyncDirection,
        updated_after: Optional[datetime] = None,
    ) -> Dict[str, int]:
        """Sync issues in one direction"""
        stats = {
            "created": 0,
            "updated": 0,
            "conflicts": 0,
            "skipped": 0,
            "skipped_inaccessible": 0,
            "skipped_notes_inaccessible": 0,
            "errors": 0,
        }

        try:
            # Get all issues from source
            source_issues = source_client.get_issues(source_project_id, updated_after=updated_after)

            for source_issue in source_issues:
                try:
                    # Find existing sync record
                    if direction == SyncDirection.SOURCE_TO_TARGET:
                        synced_issue = (
                            self.db.query(SyncedIssue)
                            .filter(
                                SyncedIssue.project_pair_id == project_pair.id,
                                SyncedIssue.source_issue_iid == source_issue.iid,
                            )
                            .first()
                        )
                    else:
                        synced_issue = (
                            self.db.query(SyncedIssue)
                            .filter(
                                SyncedIssue.project_pair_id == project_pair.id,
                                SyncedIssue.target_issue_iid == source_issue.iid,
                            )
                            .first()
                        )

                    if synced_issue:
                        # Issue already synced, check for updates
                        target_issue_iid = (
                            synced_issue.target_issue_iid
                            if direction == SyncDirection.SOURCE_TO_TARGET
                            else synced_issue.source_issue_iid
                        )
                        target_issue, rc = target_client.get_issue_optional(
                            target_project_id, target_issue_iid
                        )
                        if target_issue is None:
                            # Distinguish "deleted" from "inaccessible" so we don't create duplicates on 403.
                            if rc in (401, 403):
                                logger.warning(
                                    f"Skipping issue #{source_issue.iid}: target issue #{target_issue_iid} inaccessible (HTTP {rc})"
                                )
                                stats["skipped_inaccessible"] += 1
                                self._log_sync(
                                    project_pair,
                                    SyncStatus.SKIPPED,
                                    direction,
                                    f"Skipped: target issue inaccessible (HTTP {rc})",
                                    source_iid=source_issue.iid,
                                    target_iid=target_issue_iid,
                                )
                                continue
                            if rc == 404:
                                # Target-side issue was deleted; recreate it and repair mapping.
                                recreated = self._create_issue_from_source(
                                    source_issue,
                                    source_instance,
                                    target_client,
                                    target_project_id,
                                    target_instance.id,
                                    source_project_id,
                                    target_catch_all_username=getattr(
                                        target_instance, "catch_all_username", None
                                    ),
                                    stats=stats,
                                )
                                if direction == SyncDirection.SOURCE_TO_TARGET:
                                    synced_issue.target_issue_iid = recreated.iid
                                    synced_issue.target_issue_id = recreated.id
                                else:
                                    synced_issue.source_issue_iid = recreated.iid
                                    synced_issue.source_issue_id = recreated.id
                                synced_issue.last_synced_at = self._utcnow()
                                synced_issue.sync_hash = self._compute_synced_hash(
                                    source_issue,
                                    source_instance_url=source_instance.url,
                                    source_project_id=source_project_id,
                                )
                                self.db.commit()
                                stats["updated"] += 1
                                continue
                            raise RuntimeError(
                                f"Failed to fetch target issue {target_issue_iid} (HTTP {rc})"
                            )

                        # Detect conflicts
                        if self._detect_conflict(synced_issue, source_issue, target_issue):
                            self._log_conflict(
                                project_pair,
                                synced_issue,
                                source_issue,
                                target_issue,
                                "concurrent_update",
                            )
                            stats["conflicts"] += 1
                            continue

                        # Check if source was updated since last sync
                        source_updated = self._parse_gitlab_datetime(source_issue.updated_at)
                        last_synced_at = self._normalize_utc_naive(synced_issue.last_synced_at)
                        # GitLab timestamps are often second-granularity while our DB stores microseconds,
                        # and GitLab/server clocks can be slightly skewed relative to the worker clock.
                        # In bidirectional runs, one direction can update `last_synced_at` and the reverse
                        # direction may then miss legitimate updates (especially comment-only updates).
                        # Apply a tolerance window to reduce false "no update" decisions.
                        compare_after = (
                            (last_synced_at - timedelta(minutes=2))
                            if last_synced_at is not None
                            else None
                        )
                        source_hash = self._compute_synced_hash(
                            source_issue,
                            source_instance_url=source_instance.url,
                            source_project_id=source_project_id,
                        )

                        if synced_issue.sync_hash != source_hash and (
                            compare_after is None or source_updated > compare_after
                        ):
                            # Update target issue
                            self._update_issue_from_source(
                                source_issue,
                                target_issue_iid,
                                source_instance,
                                target_client,
                                target_project_id,
                                target_instance.id,
                                source_project_id,
                                target_catch_all_username=getattr(
                                    target_instance, "catch_all_username", None
                                ),
                                stats=stats,
                            )
                            synced_issue.last_synced_at = self._utcnow()
                            synced_issue.sync_hash = source_hash
                            self.db.commit()
                            stats["updated"] += 1
                        elif compare_after is None or source_updated > compare_after:
                            # Likely comment-only or system updates; keep issue content but still sync comments.
                            self._sync_comments(
                                source_issue,
                                target_issue,
                                source_instance,
                                target_client,
                                target_project_id,
                                target_instance.id,
                                source_project_id,
                                stats=stats,
                            )
                            synced_issue.last_synced_at = self._utcnow()
                            self.db.commit()
                            stats["updated"] += 1
                        else:
                            stats["skipped"] += 1
                    else:
                        # If this issue looks like it was previously synced from the other side (based on our
                        # embedded reference), avoid creating duplicates and instead rebuild the mapping.
                        ref = self._parse_sync_reference(getattr(source_issue, "description", None))
                        if ref is not None:
                            ref_url, ref_iid = ref
                            if self._normalize_instance_url(target_instance.url) == ref_url:
                                other_issue, rc = target_client.get_issue_optional(
                                    target_project_id, ref_iid
                                )
                                if other_issue is not None:
                                    source_hash = self._compute_synced_hash(
                                        source_issue,
                                        source_instance_url=source_instance.url,
                                        source_project_id=source_project_id,
                                    )
                                    if direction == SyncDirection.SOURCE_TO_TARGET:
                                        rebuilt = SyncedIssue(
                                            project_pair_id=project_pair.id,
                                            source_issue_iid=source_issue.iid,
                                            source_issue_id=source_issue.id,
                                            target_issue_iid=other_issue.iid,
                                            target_issue_id=other_issue.id,
                                            sync_hash=source_hash,
                                            last_synced_at=self._utcnow(),
                                        )
                                    else:
                                        # Direction is TARGET_TO_SOURCE; the "other issue" lives on the real source side.
                                        rebuilt = SyncedIssue(
                                            project_pair_id=project_pair.id,
                                            source_issue_iid=other_issue.iid,
                                            source_issue_id=other_issue.id,
                                            target_issue_iid=source_issue.iid,
                                            target_issue_id=source_issue.id,
                                            sync_hash=source_hash,
                                            last_synced_at=self._utcnow(),
                                        )

                                    if self._safe_commit_synced_issue(rebuilt):
                                        stats["created"] += 1
                                    else:
                                        stats["skipped"] += 1
                                    continue
                                if rc in (401, 403):
                                    # Don't create a duplicate if we can see it's a mirrored issue but can't access the pair.
                                    logger.warning(
                                        f"Skipping issue #{source_issue.iid}: mirrored target issue #{ref_iid} inaccessible (HTTP {rc})"
                                    )
                                    stats["skipped_inaccessible"] += 1
                                    self._log_sync(
                                        project_pair,
                                        SyncStatus.SKIPPED,
                                        direction,
                                        f"Skipped: mirrored target issue inaccessible (HTTP {rc})",
                                        source_iid=source_issue.iid,
                                        target_iid=ref_iid,
                                    )
                                    continue

                        # New issue, create in target
                        target_issue = self._create_issue_from_source(
                            source_issue,
                            source_instance,
                            target_client,
                            target_project_id,
                            target_instance.id,
                            source_project_id,
                            target_catch_all_username=getattr(target_instance, "catch_all_username", None),
                            stats=stats,
                        )

                        # Create sync record
                        if direction == SyncDirection.SOURCE_TO_TARGET:
                            source_hash = self._compute_synced_hash(
                                source_issue,
                                source_instance_url=source_instance.url,
                                source_project_id=source_project_id,
                            )
                            synced_issue = SyncedIssue(
                                project_pair_id=project_pair.id,
                                source_issue_iid=source_issue.iid,
                                source_issue_id=source_issue.id,
                                target_issue_iid=target_issue.iid,
                                target_issue_id=target_issue.id,
                                sync_hash=source_hash,
                            )
                        else:
                            source_hash = self._compute_synced_hash(
                                source_issue,
                                source_instance_url=source_instance.url,
                                source_project_id=source_project_id,
                            )
                            synced_issue = SyncedIssue(
                                project_pair_id=project_pair.id,
                                source_issue_iid=target_issue.iid,
                                source_issue_id=target_issue.id,
                                target_issue_iid=source_issue.iid,
                                target_issue_id=source_issue.id,
                                sync_hash=source_hash,
                            )
                        if self._safe_commit_synced_issue(synced_issue):
                            stats["created"] += 1
                        else:
                            stats["skipped"] += 1

                except Exception as e:
                    # Ensure a single issue failure doesn't poison the session for the rest of the run.
                    try:
                        self.db.rollback()
                    except Exception:
                        pass
                    logger.error(f"Failed to sync issue #{source_issue.iid}: {e}")
                    stats["errors"] += 1
                    self._log_sync(
                        project_pair,
                        SyncStatus.FAILED,
                        direction,
                        f"Failed to sync issue: {str(e)}",
                        source_iid=source_issue.iid,
                    )

        except Exception as e:
            logger.error(f"Failed to sync direction {direction}: {e}")
            raise

        return stats
