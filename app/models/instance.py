"""GitLab instance model"""
from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from app.models.base import Base


class GitLabInstance(Base):
    """GitLab instance configuration"""

    __tablename__ = "gitlab_instances"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    url = Column(String, nullable=False)
    access_token = Column(String, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<GitLabInstance(name='{self.name}', url='{self.url}')>"
