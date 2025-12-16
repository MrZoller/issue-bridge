"""Project pair management endpoints"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models import GitLabInstance, ProjectPair
from app.models.base import get_db
from app.scheduler import scheduler

router = APIRouter(prefix="/api/project-pairs", tags=["project-pairs"])


class ProjectPairCreate(BaseModel):
    # Optional: if omitted/blank, we auto-generate a readable name
    name: Optional[str] = None
    source_instance_id: int
    source_project_id: str
    target_instance_id: int
    target_project_id: str
    bidirectional: bool = True
    sync_enabled: bool = True
    sync_interval_minutes: int = 10
    # Optional comma-separated allowlist of issue fields to sync for this pair.
    # If omitted/blank, defaults are used.
    sync_fields: Optional[str] = None


class ProjectPairResponse(BaseModel):
    id: int
    name: str
    source_instance_id: int
    source_project_id: str
    target_instance_id: int
    target_project_id: str
    sync_enabled: bool
    bidirectional: bool
    sync_interval_minutes: int
    sync_fields: Optional[str]
    created_at: datetime
    updated_at: datetime
    last_sync_at: Optional[datetime]

    class Config:
        from_attributes = True


@router.get("/", response_model=List[ProjectPairResponse])
def list_project_pairs(db: Session = Depends(get_db)):
    """List all project pairs"""
    pairs = db.query(ProjectPair).all()
    return pairs


def _generate_project_pair_name(
    db: Session,
    *,
    source_instance_id: int,
    source_project_id: str,
    target_instance_id: int,
    target_project_id: str,
    exclude_pair_id: Optional[int] = None,
) -> str:
    """Generate a readable, unique project pair name.

    Format: "<source instance>:<source project> <-> <target instance>:<target project>"
    """
    source_instance = (
        db.query(GitLabInstance).filter(GitLabInstance.id == source_instance_id).first()
    )
    target_instance = (
        db.query(GitLabInstance).filter(GitLabInstance.id == target_instance_id).first()
    )
    source_name = source_instance.name if source_instance else f"instance-{source_instance_id}"
    target_name = target_instance.name if target_instance else f"instance-{target_instance_id}"

    base = f"{source_name}:{source_project_id} <-> {target_name}:{target_project_id}"

    candidate = base
    suffix = 2
    while True:
        q = db.query(ProjectPair).filter(ProjectPair.name == candidate)
        if exclude_pair_id is not None:
            q = q.filter(ProjectPair.id != exclude_pair_id)
        if q.first() is None:
            return candidate
        candidate = f"{base} ({suffix})"
        suffix += 1


@router.post("/", response_model=ProjectPairResponse)
def create_project_pair(pair: ProjectPairCreate, db: Session = Depends(get_db)):
    """Create a new project pair"""
    requested_name = (pair.name or "").strip()
    if requested_name:
        # Check if name already exists
        existing = db.query(ProjectPair).filter(ProjectPair.name == requested_name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Project pair name already exists")
        final_name = requested_name
    else:
        final_name = _generate_project_pair_name(
            db,
            source_instance_id=pair.source_instance_id,
            source_project_id=pair.source_project_id,
            target_instance_id=pair.target_instance_id,
            target_project_id=pair.target_project_id,
        )

    payload = pair.dict()
    payload["name"] = final_name
    db_pair = ProjectPair(**payload)
    db.add(db_pair)
    db.commit()
    db.refresh(db_pair)

    # Schedule immediately if enabled
    if db_pair.sync_enabled:
        scheduler.schedule_pair(db_pair.id, db_pair.sync_interval_minutes)
    return db_pair


@router.get("/{pair_id}", response_model=ProjectPairResponse)
def get_project_pair(pair_id: int, db: Session = Depends(get_db)):
    """Get a specific project pair"""
    pair = db.query(ProjectPair).filter(ProjectPair.id == pair_id).first()
    if not pair:
        raise HTTPException(status_code=404, detail="Project pair not found")
    return pair


@router.put("/{pair_id}", response_model=ProjectPairResponse)
def update_project_pair(pair_id: int, pair: ProjectPairCreate, db: Session = Depends(get_db)):
    """Update a project pair"""
    db_pair = db.query(ProjectPair).filter(ProjectPair.id == pair_id).first()
    if not db_pair:
        raise HTTPException(status_code=404, detail="Project pair not found")

    requested_name = (pair.name or "").strip()
    if requested_name:
        existing = (
            db.query(ProjectPair)
            .filter(ProjectPair.name == requested_name, ProjectPair.id != pair_id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="Project pair name already exists")
        final_name = requested_name
    else:
        final_name = _generate_project_pair_name(
            db,
            source_instance_id=pair.source_instance_id,
            source_project_id=pair.source_project_id,
            target_instance_id=pair.target_instance_id,
            target_project_id=pair.target_project_id,
            exclude_pair_id=pair_id,
        )

    for key, value in pair.dict().items():
        if key == "name":
            continue
        setattr(db_pair, key, value)
    db_pair.name = final_name

    db.commit()
    db.refresh(db_pair)

    # Reconcile scheduler with latest DB state
    if db_pair.sync_enabled:
        scheduler.schedule_pair(db_pair.id, db_pair.sync_interval_minutes)
    else:
        scheduler.unschedule_pair(db_pair.id)
    return db_pair


@router.delete("/{pair_id}")
def delete_project_pair(pair_id: int, db: Session = Depends(get_db)):
    """Delete a project pair"""
    pair = db.query(ProjectPair).filter(ProjectPair.id == pair_id).first()
    if not pair:
        raise HTTPException(status_code=404, detail="Project pair not found")

    # Ensure any scheduled job is removed
    scheduler.unschedule_pair(pair_id)
    db.delete(pair)
    db.commit()
    return {"message": "Project pair deleted successfully"}


@router.post("/{pair_id}/toggle")
def toggle_sync(pair_id: int, db: Session = Depends(get_db)):
    """Toggle sync enabled/disabled for a project pair"""
    pair = db.query(ProjectPair).filter(ProjectPair.id == pair_id).first()
    if not pair:
        raise HTTPException(status_code=404, detail="Project pair not found")

    pair.sync_enabled = not pair.sync_enabled
    db.commit()
    db.refresh(pair)

    # Apply scheduling change immediately
    if pair.sync_enabled:
        scheduler.schedule_pair(pair.id, pair.sync_interval_minutes)
    else:
        scheduler.unschedule_pair(pair.id)
    return pair
