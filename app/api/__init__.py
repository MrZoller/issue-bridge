"""API routes"""

from app.api import dashboard, instances, project_pairs, sync, user_mappings

__all__ = ["instances", "project_pairs", "user_mappings", "sync", "dashboard"]
