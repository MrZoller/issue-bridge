"""Sync management endpoints"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.models.base import get_db
from app.models import SyncLog, Conflict, SyncedIssue
from app.models.sync_log import SyncStatus
from app.services.sync_service import SyncService

router = APIRouter(prefix="/api/sync", tags=["sync"])


class SyncLogResponse(BaseModel):
    id: int
    project_pair_id: int
    source_issue_iid: Optional[int] = None
    target_issue_iid: Optional[int] = None
    status: str
    direction: Optional[str] = None
    message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConflictResponse(BaseModel):
    id: int
    project_pair_id: int
    source_issue_iid: int
    target_issue_iid: Optional[int] = None
    conflict_type: str
    description: str
    resolved: bool
    created_at: datetime

    class Config:
        from_attributes = True


class SyncedIssueResponse(BaseModel):
    id: int
    project_pair_id: int
    source_issue_iid: int
    target_issue_iid: int
    last_synced_at: datetime

    class Config:
        from_attributes = True


@router.post("/{pair_id}/trigger")
def trigger_sync(pair_id: int, db: Session = Depends(get_db)):
    """Manually trigger sync for a project pair"""
    sync_service = SyncService(db)
    try:
        result = sync_service.sync_project_pair(pair_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{pair_id}/repair-mappings")
def repair_mappings(pair_id: int, db: Session = Depends(get_db)):
    """Rebuild SyncedIssue rows from embedded sync markers (safe, non-destructive)."""
    sync_service = SyncService(db)
    try:
        return sync_service.repair_mappings(pair_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs", response_model=List[SyncLogResponse])
def list_sync_logs(
    limit: int = 100,
    project_pair_id: int = None,
    db: Session = Depends(get_db)
):
    """List sync logs"""
    query = db.query(SyncLog).order_by(SyncLog.created_at.desc())
    if project_pair_id:
        query = query.filter(SyncLog.project_pair_id == project_pair_id)
    logs = query.limit(limit).all()
    return logs


@router.get("/conflicts", response_model=List[ConflictResponse])
def list_conflicts(
    resolved: bool = None,
    project_pair_id: int = None,
    db: Session = Depends(get_db)
):
    """List conflicts"""
    query = db.query(Conflict).order_by(Conflict.created_at.desc())
    if resolved is not None:
        query = query.filter(Conflict.resolved == resolved)
    if project_pair_id:
        query = query.filter(Conflict.project_pair_id == project_pair_id)
    conflicts = query.all()
    return conflicts


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(
    conflict_id: int,
    request: Request,
    resolution_notes: Optional[str] = Body(None, embed=True),
    db: Session = Depends(get_db)
):
    """Mark a conflict as resolved"""
    # Backwards compatibility: older clients may still pass ?resolution_notes=...
    if resolution_notes is None:
        resolution_notes = request.query_params.get("resolution_notes")

    conflict = db.query(Conflict).filter(Conflict.id == conflict_id).first()
    if not conflict:
        raise HTTPException(status_code=404, detail="Conflict not found")

    conflict.resolved = True
    conflict.resolved_at = datetime.utcnow()
    conflict.resolution_notes = resolution_notes
    db.commit()
    db.refresh(conflict)
    return conflict


@router.get("/synced-issues", response_model=List[SyncedIssueResponse])
def list_synced_issues(
    project_pair_id: int = None,
    db: Session = Depends(get_db)
):
    """List synced issues"""
    query = db.query(SyncedIssue).order_by(SyncedIssue.last_synced_at.desc())
    if project_pair_id:
        query = query.filter(SyncedIssue.project_pair_id == project_pair_id)
    issues = query.all()
    return issues
