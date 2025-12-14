"""Dashboard and statistics endpoints"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import Conflict, ProjectPair, SyncedIssue, SyncLog
from app.models.base import get_db
from app.models.sync_log import SyncStatus

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Get dashboard statistics"""
    # Total counts
    total_pairs = db.query(ProjectPair).count()
    active_pairs = db.query(ProjectPair).filter(ProjectPair.sync_enabled == True).count()
    total_synced_issues = db.query(SyncedIssue).count()
    unresolved_conflicts = db.query(Conflict).filter(Conflict.resolved == False).count()

    # Recent sync activity (last 24 hours)
    last_24h = datetime.utcnow() - timedelta(hours=24)
    recent_syncs = db.query(SyncLog).filter(SyncLog.created_at >= last_24h).count()
    recent_successes = (
        db.query(SyncLog)
        .filter(SyncLog.created_at >= last_24h, SyncLog.status == SyncStatus.SUCCESS)
        .count()
    )
    recent_failures = (
        db.query(SyncLog)
        .filter(SyncLog.created_at >= last_24h, SyncLog.status == SyncStatus.FAILED)
        .count()
    )

    # Per project pair stats
    pair_stats = []
    pairs = db.query(ProjectPair).all()
    for pair in pairs:
        synced_issues_count = (
            db.query(SyncedIssue).filter(SyncedIssue.project_pair_id == pair.id).count()
        )
        conflicts_count = (
            db.query(Conflict)
            .filter(Conflict.project_pair_id == pair.id, Conflict.resolved == False)
            .count()
        )

        last_log = (
            db.query(SyncLog)
            .filter(SyncLog.project_pair_id == pair.id)
            .order_by(desc(SyncLog.created_at))
            .first()
        )

        pair_stats.append(
            {
                "id": pair.id,
                "name": pair.name,
                "sync_enabled": pair.sync_enabled,
                "bidirectional": pair.bidirectional,
                "last_sync_at": pair.last_sync_at,
                "synced_issues": synced_issues_count,
                "unresolved_conflicts": conflicts_count,
                "last_status": last_log.status if last_log else None,
                "last_message": last_log.message if last_log else None,
            }
        )

    return {
        "total_pairs": total_pairs,
        "active_pairs": active_pairs,
        "total_synced_issues": total_synced_issues,
        "unresolved_conflicts": unresolved_conflicts,
        "recent_syncs": recent_syncs,
        "recent_successes": recent_successes,
        "recent_failures": recent_failures,
        "pair_stats": pair_stats,
    }


@router.get("/activity")
def get_recent_activity(limit: int = 50, db: Session = Depends(get_db)):
    """Get recent sync activity"""
    logs = db.query(SyncLog).order_by(desc(SyncLog.created_at)).limit(limit).all()

    activity = []
    for log in logs:
        activity.append(
            {
                "id": log.id,
                "project_pair_id": log.project_pair_id,
                "status": log.status,
                "direction": log.direction,
                "message": log.message,
                "source_issue_iid": log.source_issue_iid,
                "target_issue_iid": log.target_issue_iid,
                "created_at": log.created_at,
            }
        )

    return activity
