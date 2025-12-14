"""Sync log model"""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.models.base import Base


class SyncStatus(str, enum.Enum):
    """Sync status enumeration"""
    SUCCESS = "success"
    FAILED = "failed"
    CONFLICT = "conflict"
    SKIPPED = "skipped"


class SyncDirection(str, enum.Enum):
    """Sync direction enumeration"""
    SOURCE_TO_TARGET = "source_to_target"
    TARGET_TO_SOURCE = "target_to_source"


class SyncLog(Base):
    """Log of sync operations"""

    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Project pair
    project_pair_id = Column(Integer, ForeignKey("project_pairs.id"), nullable=False)

    # Issue information
    source_issue_iid = Column(Integer, nullable=True)
    target_issue_iid = Column(Integer, nullable=True)

    # Sync details
    status = Column(Enum(SyncStatus), nullable=False)
    direction = Column(Enum(SyncDirection), nullable=True)
    message = Column(Text, nullable=True)
    details = Column(Text, nullable=True)  # JSON or additional details

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    project_pair = relationship("ProjectPair")

    def __repr__(self):
        return f"<SyncLog(status={self.status}, direction={self.direction})>"
