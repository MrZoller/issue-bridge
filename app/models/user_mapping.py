"""User mapping model"""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base


class UserMapping(Base):
    """Username mapping between GitLab instances"""

    __tablename__ = "user_mappings"
    __table_args__ = (
        UniqueConstraint("source_instance_id", "source_username", name="uq_source_user"),
        UniqueConstraint("target_instance_id", "target_username", name="uq_target_user"),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Source user
    source_instance_id = Column(Integer, ForeignKey("gitlab_instances.id"), nullable=False)
    source_username = Column(String, nullable=False, index=True)

    # Target user
    target_instance_id = Column(Integer, ForeignKey("gitlab_instances.id"), nullable=False)
    target_username = Column(String, nullable=False, index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    source_instance = relationship("GitLabInstance", foreign_keys=[source_instance_id])
    target_instance = relationship("GitLabInstance", foreign_keys=[target_instance_id])

    def __repr__(self):
        return f"<UserMapping({self.source_username} -> {self.target_username})>"
