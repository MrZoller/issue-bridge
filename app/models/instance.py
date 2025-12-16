"""GitLab instance model"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.models.base import Base


class GitLabInstance(Base):
    """GitLab instance configuration"""

    __tablename__ = "gitlab_instances"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    url = Column(String, nullable=False)
    access_token = Column(String, nullable=False)
    description = Column(String, nullable=True)
    # Optional "catch-all" username used when no explicit user mapping exists.
    # If unset/empty, unmapped usernames are ignored (current behavior).
    catch_all_username = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<GitLabInstance(name='{self.name}', url='{self.url}')>"
