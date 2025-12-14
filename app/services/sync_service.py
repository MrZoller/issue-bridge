"""Issue synchronization service"""
import logging
import hashlib
import json
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models import (
    ProjectPair,
    GitLabInstance,
    SyncedIssue,
    SyncLog,
    Conflict,
    UserMapping,
)
from app.models.sync_log import SyncStatus, SyncDirection
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

    def _get_client(self, instance_id: int) -> GitLabClient:
        """Get or create GitLab client for instance"""
        if instance_id not in self.clients:
            instance = self.db.query(GitLabInstance).filter(
                GitLabInstance.id == instance_id
            ).first()
            if not instance:
                raise ValueError(f"GitLab instance {instance_id} not found")
            self.clients[instance_id] = GitLabClient(instance.url, instance.access_token)
        return self.clients[instance_id]

    def _get_user_mapping(
        self, username: str, source_instance_id: int, target_instance_id: int
    ) -> Optional[str]:
        """Get mapped username for target instance"""
        mapping = self.db.query(UserMapping).filter(
            UserMapping.source_instance_id == source_instance_id,
            UserMapping.source_username == username,
            UserMapping.target_instance_id == target_instance_id,
        ).first()
        return mapping.target_username if mapping else None

    def _map_usernames(
        self, usernames: List[str], source_instance_id: int, target_instance_id: int
    ) -> List[str]:
        """Map list of usernames to target instance"""
        mapped = []
        for username in usernames:
            mapped_username = self._get_user_mapping(
                username, source_instance_id, target_instance_id
            )
            if mapped_username:
                mapped.append(mapped_username)
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
        data = {
            "title": issue.title,
            "description": issue.description or "",
            "state": issue.state,
            "labels": sorted(issue.labels),
            "updated_at": issue.updated_at,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def _add_sync_reference(self, description: str, instance_url: str, issue_iid: int) -> str:
        """Add sync reference to issue description"""
        sync_note = f"\n\n---\n*Synced from: {instance_url}/-/issues/{issue_iid}*"
        if sync_note not in (description or ""):
            return (description or "") + sync_note
        return description or ""

    def _create_issue_from_source(
        self,
        source_issue: Any,
        source_instance: GitLabInstance,
        target_client: GitLabClient,
        target_project_id: str,
        target_instance_id: int,
    ) -> Any:
        """Create a new issue in target from source issue"""
        # Map assignees
        assignee_ids = []
        if hasattr(source_issue, 'assignees') and source_issue.assignees:
            assignee_usernames = [a['username'] for a in source_issue.assignees]
            mapped_usernames = self._map_usernames(
                assignee_usernames, source_instance.id, target_instance_id
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
        if hasattr(source_issue, 'milestone') and source_issue.milestone:
            milestone_id = self._ensure_milestone(
                target_client, target_project_id, source_issue.milestone['title']
            )

        # Prepare issue data
        issue_data = {
            "title": source_issue.title,
            "description": self._add_sync_reference(
                source_issue.description, source_instance.url, source_issue.iid
            ),
            "labels": source_issue.labels if source_issue.labels else [],
        }

        if assignee_ids:
            issue_data["assignee_ids"] = assignee_ids

        if milestone_id:
            issue_data["milestone_id"] = milestone_id

        if hasattr(source_issue, 'due_date') and source_issue.due_date:
            issue_data["due_date"] = source_issue.due_date

        # Create issue
        target_issue = target_client.create_issue(target_project_id, issue_data)

        # Sync comments
        self._sync_comments(
            source_issue, target_issue, source_instance,
            target_client, target_project_id, target_instance_id
        )

        # Close issue if source is closed
        if source_issue.state == "closed":
            target_client.update_issue(target_project_id, target_issue.iid, {"state_event": "close"})

        return target_issue

    def _sync_comments(
        self,
        source_issue: Any,
        target_issue: Any,
        source_instance: GitLabInstance,
        target_client: GitLabClient,
        target_project_id: str,
        target_instance_id: int,
    ):
        """Sync comments from source to target issue"""
        try:
            source_client = self._get_client(source_instance.id)
            source_notes = source_client.get_issue_notes(
                str(source_issue.project_id), source_issue.iid
            )

            # Get existing target notes to avoid duplicates
            target_notes = target_client.get_issue_notes(target_project_id, target_issue.iid)
            existing_note_bodies = {note.body for note in target_notes}

            for note in source_notes:
                # Skip system notes
                if note.system:
                    continue

                # Format note with author attribution
                author_note = f"**Comment by @{note.author['username']}:**\n\n{note.body}"

                # Skip if already synced
                if author_note in existing_note_bodies:
                    continue

                target_client.create_issue_note(target_project_id, target_issue.iid, author_note)

        except Exception as e:
            logger.error(f"Failed to sync comments: {e}")

    def _update_issue_from_source(
        self,
        source_issue: Any,
        target_issue_iid: int,
        source_instance: GitLabInstance,
        target_client: GitLabClient,
        target_project_id: str,
        target_instance_id: int,
    ):
        """Update existing target issue from source"""
        # Map assignees
        assignee_ids = []
        if hasattr(source_issue, 'assignees') and source_issue.assignees:
            assignee_usernames = [a['username'] for a in source_issue.assignees]
            mapped_usernames = self._map_usernames(
                assignee_usernames, source_instance.id, target_instance_id
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
        if hasattr(source_issue, 'milestone') and source_issue.milestone:
            milestone_id = self._ensure_milestone(
                target_client, target_project_id, source_issue.milestone['title']
            )

        # Prepare update data
        update_data = {
            "title": source_issue.title,
            "description": self._add_sync_reference(
                source_issue.description, source_instance.url, source_issue.iid
            ),
            "labels": source_issue.labels if source_issue.labels else [],
        }

        if assignee_ids:
            update_data["assignee_ids"] = assignee_ids

        if milestone_id:
            update_data["milestone_id"] = milestone_id

        if hasattr(source_issue, 'due_date') and source_issue.due_date:
            update_data["due_date"] = source_issue.due_date

        # Handle state changes
        target_issue = target_client.get_issue(target_project_id, target_issue_iid)
        if source_issue.state != target_issue.state:
            update_data["state_event"] = "close" if source_issue.state == "closed" else "reopen"

        # Update issue
        target_client.update_issue(target_project_id, target_issue_iid, update_data)

        # Sync new comments
        self._sync_comments(
            source_issue, target_issue, source_instance,
            target_client, target_project_id, target_instance_id
        )

    def _detect_conflict(
        self, synced_issue: SyncedIssue, source_issue: Any, target_issue: Any
    ) -> bool:
        """Detect if both issues were updated since last sync"""
        source_updated = self._parse_gitlab_datetime(source_issue.updated_at)
        target_updated = self._parse_gitlab_datetime(target_issue.updated_at)
        last_synced_at = self._normalize_utc_naive(synced_issue.last_synced_at)

        # If both were updated after last sync, we have a conflict
        if last_synced_at:
            return (
                source_updated > last_synced_at
                and target_updated > last_synced_at
            )
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
            source_data=json.dumps({
                "title": source_issue.title,
                "state": source_issue.state,
                "updated_at": source_issue.updated_at,
            }),
            target_data=json.dumps({
                "title": target_issue.title,
                "state": target_issue.state,
                "updated_at": target_issue.updated_at,
            }) if target_issue else None,
        )
        try:
            self.db.add(conflict)
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to persist conflict log ({conflict_type}): {e}")
            return

        logger.warning(
            f"Conflict detected: {conflict_type} for source issue #{source_issue.iid}"
        )

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

    def sync_project_pair(self, project_pair_id: int) -> Dict[str, Any]:
        """Sync issues for a project pair"""
        project_pair = self.db.query(ProjectPair).filter(
            ProjectPair.id == project_pair_id
        ).first()

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
            "errors": 0,
        }

        try:
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
                )
                for key in stats:
                    stats[key] += stats_t2s[key]

            # Update last sync time
            project_pair.last_sync_at = self._utcnow()
            self.db.commit()

            logger.info(f"Sync completed for {project_pair.name}: {stats}")
            self._log_sync(
                project_pair,
                SyncStatus.SUCCESS,
                message=f"Sync completed: {stats}"
            )

            return {"status": "success", "stats": stats}

        except Exception as e:
            logger.error(f"Sync failed for {project_pair.name}: {e}")
            self._log_sync(
                project_pair,
                SyncStatus.FAILED,
                message=f"Sync failed: {str(e)}"
            )
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
    ) -> Dict[str, int]:
        """Sync issues in one direction"""
        stats = {
            "created": 0,
            "updated": 0,
            "conflicts": 0,
            "skipped": 0,
            "errors": 0,
        }

        try:
            # Get all issues from source
            source_issues = source_client.get_issues(source_project_id)

            for source_issue in source_issues:
                try:
                    # Find existing sync record
                    if direction == SyncDirection.SOURCE_TO_TARGET:
                        synced_issue = self.db.query(SyncedIssue).filter(
                            SyncedIssue.project_pair_id == project_pair.id,
                            SyncedIssue.source_issue_iid == source_issue.iid,
                        ).first()
                    else:
                        synced_issue = self.db.query(SyncedIssue).filter(
                            SyncedIssue.project_pair_id == project_pair.id,
                            SyncedIssue.target_issue_iid == source_issue.iid,
                        ).first()

                    if synced_issue:
                        # Issue already synced, check for updates
                        target_issue_iid = (synced_issue.target_issue_iid if direction == SyncDirection.SOURCE_TO_TARGET
                                           else synced_issue.source_issue_iid)
                        target_issue = target_client.get_issue(target_project_id, target_issue_iid)

                        # Detect conflicts
                        if self._detect_conflict(synced_issue, source_issue, target_issue):
                            self._log_conflict(
                                project_pair, synced_issue, source_issue, target_issue,
                                "concurrent_update"
                            )
                            stats["conflicts"] += 1
                            continue

                        # Check if source was updated since last sync
                        source_updated = self._parse_gitlab_datetime(source_issue.updated_at)
                        last_synced_at = self._normalize_utc_naive(synced_issue.last_synced_at)
                        if last_synced_at is None or source_updated > last_synced_at:
                            # Update target issue
                            self._update_issue_from_source(
                                source_issue, target_issue_iid, source_instance,
                                target_client, target_project_id, target_instance.id
                            )
                            synced_issue.last_synced_at = self._utcnow()
                            synced_issue.sync_hash = self._compute_issue_hash(source_issue)
                            self.db.commit()
                            stats["updated"] += 1
                        else:
                            stats["skipped"] += 1
                    else:
                        # New issue, create in target
                        target_issue = self._create_issue_from_source(
                            source_issue, source_instance, target_client,
                            target_project_id, target_instance.id
                        )

                        # Create sync record
                        if direction == SyncDirection.SOURCE_TO_TARGET:
                            synced_issue = SyncedIssue(
                                project_pair_id=project_pair.id,
                                source_issue_iid=source_issue.iid,
                                source_issue_id=source_issue.id,
                                target_issue_iid=target_issue.iid,
                                target_issue_id=target_issue.id,
                                sync_hash=self._compute_issue_hash(source_issue),
                            )
                        else:
                            synced_issue = SyncedIssue(
                                project_pair_id=project_pair.id,
                                source_issue_iid=target_issue.iid,
                                source_issue_id=target_issue.id,
                                target_issue_iid=source_issue.iid,
                                target_issue_id=source_issue.id,
                                sync_hash=self._compute_issue_hash(source_issue),
                            )
                        self.db.add(synced_issue)
                        self.db.commit()
                        stats["created"] += 1

                except Exception as e:
                    logger.error(f"Failed to sync issue #{source_issue.iid}: {e}")
                    stats["errors"] += 1
                    self._log_sync(
                        project_pair, SyncStatus.FAILED, direction,
                        f"Failed to sync issue: {str(e)}",
                        source_iid=source_issue.iid
                    )

        except Exception as e:
            logger.error(f"Failed to sync direction {direction}: {e}")
            raise

        return stats
