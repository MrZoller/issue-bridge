"""Project pair management endpoints"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models import ProjectPair
from app.models.base import get_db
from app.scheduler import scheduler

router = APIRouter(prefix="/api/project-pairs", tags=["project-pairs"])


class ProjectPairCreate(BaseModel):
    name: str
    source_instance_id: int
    source_project_id: str
    target_instance_id: int
    target_project_id: str
    bidirectional: bool = True
    sync_enabled: bool = True
    sync_interval_minutes: int = 10


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


@router.post("/", response_model=ProjectPairResponse)
def create_project_pair(pair: ProjectPairCreate, db: Session = Depends(get_db)):
    """Create a new project pair"""
    # Check if name already exists
    existing = db.query(ProjectPair).filter(ProjectPair.name == pair.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Project pair name already exists")

    db_pair = ProjectPair(**pair.dict())
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

    for key, value in pair.dict().items():
        setattr(db_pair, key, value)

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
