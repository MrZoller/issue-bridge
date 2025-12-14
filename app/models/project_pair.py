"""Project pair model"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import Base


class ProjectPair(Base):
    """Project pair configuration for syncing"""

    __tablename__ = "project_pairs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)

    # Source instance and project
    source_instance_id = Column(Integer, ForeignKey("gitlab_instances.id"), nullable=False)
    source_project_id = Column(String, nullable=False)  # GitLab project ID or path

    # Target instance and project
    target_instance_id = Column(Integer, ForeignKey("gitlab_instances.id"), nullable=False)
    target_project_id = Column(String, nullable=False)  # GitLab project ID or path

    # Sync configuration
    sync_enabled = Column(Boolean, default=True)
    bidirectional = Column(Boolean, default=True)
    sync_interval_minutes = Column(Integer, default=10)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_sync_at = Column(DateTime, nullable=True)

    # Relationships
    source_instance = relationship("GitLabInstance", foreign_keys=[source_instance_id])
    target_instance = relationship("GitLabInstance", foreign_keys=[target_instance_id])

    def __repr__(self):
        return f"<ProjectPair(name='{self.name}', bidirectional={self.bidirectional})>"
