"""User mapping model"""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base


class UserMapping(Base):
    """Username mapping between GitLab instances"""

    __tablename__ = "user_mappings"
    __table_args__ = (
        # Uniqueness must be scoped to the source<->target instance pair.
        # Otherwise, multi-instance setups can hit integrity errors when the same username
        # exists across different instances.
        UniqueConstraint(
            "source_instance_id",
            "source_username",
            "target_instance_id",
            name="uq_source_user_per_target_instance",
        ),
        UniqueConstraint(
            "target_instance_id",
            "target_username",
            "source_instance_id",
            name="uq_target_user_per_source_instance",
        ),
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
