"""Conflict model"""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base


class Conflict(Base):
    """Conflict log for manual resolution"""

    __tablename__ = "conflicts"

    id = Column(Integer, primary_key=True, index=True)

    # Project pair
    project_pair_id = Column(Integer, ForeignKey("project_pairs.id"), nullable=False)

    # Synced issue
    synced_issue_id = Column(Integer, ForeignKey("synced_issues.id"), nullable=True)

    # Issue information
    source_issue_iid = Column(Integer, nullable=False)
    target_issue_iid = Column(Integer, nullable=False)

    # Conflict details
    conflict_type = Column(String, nullable=False)  # e.g., "concurrent_update", "deleted_on_one_side"
    description = Column(Text, nullable=False)
    source_data = Column(Text, nullable=True)  # JSON snapshot of source
    target_data = Column(Text, nullable=True)  # JSON snapshot of target

    # Resolution
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    project_pair = relationship("ProjectPair")
    synced_issue = relationship("SyncedIssue")

    def __repr__(self):
        return f"<Conflict(type={self.conflict_type}, resolved={self.resolved})>"
