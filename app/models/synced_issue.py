"""Synced issue model"""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.models.base import Base


def utcnow() -> datetime:
    """UTC 'now' as tz-naive datetime (consistent with GitLab parsing)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SyncedIssue(Base):
    """Mapping of synced issues between instances"""

    __tablename__ = "synced_issues"
    __table_args__ = (
        UniqueConstraint("project_pair_id", "source_issue_iid", name="uq_synced_issues_pair_source_iid"),
        UniqueConstraint("project_pair_id", "target_issue_iid", name="uq_synced_issues_pair_target_iid"),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Project pair
    project_pair_id = Column(Integer, ForeignKey("project_pairs.id"), nullable=False)

    # Source issue
    source_issue_iid = Column(Integer, nullable=False)  # Issue IID on source
    source_issue_id = Column(Integer, nullable=False)   # Issue ID on source
    source_updated_at = Column(DateTime, nullable=True)

    # Target issue
    target_issue_iid = Column(Integer, nullable=False)  # Issue IID on target
    target_issue_id = Column(Integer, nullable=False)   # Issue ID on target
    target_updated_at = Column(DateTime, nullable=True)

    # Sync metadata
    last_synced_at = Column(DateTime, default=utcnow)
    sync_hash = Column(String, nullable=True)  # Hash of last synced content

    # Relationships
    project_pair = relationship("ProjectPair")

    def __repr__(self):
        return f"<SyncedIssue(source_iid={self.source_issue_iid}, target_iid={self.target_issue_iid})>"
