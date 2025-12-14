"""GitLab instance management endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from datetime import datetime

from app.models.base import get_db
from app.models import GitLabInstance

router = APIRouter(prefix="/api/instances", tags=["instances"])


class GitLabInstanceCreate(BaseModel):
    name: str
    url: str
    access_token: str
    description: str = None


class GitLabInstanceResponse(BaseModel):
    id: int
    name: str
    url: str
    description: str = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/", response_model=List[GitLabInstanceResponse])
def list_instances(db: Session = Depends(get_db)):
    """List all GitLab instances"""
    instances = db.query(GitLabInstance).all()
    return instances


@router.post("/", response_model=GitLabInstanceResponse)
def create_instance(instance: GitLabInstanceCreate, db: Session = Depends(get_db)):
    """Create a new GitLab instance"""
    # Check if name already exists
    existing = db.query(GitLabInstance).filter(
        GitLabInstance.name == instance.name
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Instance name already exists")

    db_instance = GitLabInstance(**instance.dict())
    db.add(db_instance)
    db.commit()
    db.refresh(db_instance)
    return db_instance


@router.get("/{instance_id}", response_model=GitLabInstanceResponse)
def get_instance(instance_id: int, db: Session = Depends(get_db)):
    """Get a specific GitLab instance"""
    instance = db.query(GitLabInstance).filter(
        GitLabInstance.id == instance_id
    ).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    return instance


@router.put("/{instance_id}", response_model=GitLabInstanceResponse)
def update_instance(
    instance_id: int, instance: GitLabInstanceCreate, db: Session = Depends(get_db)
):
    """Update a GitLab instance"""
    db_instance = db.query(GitLabInstance).filter(
        GitLabInstance.id == instance_id
    ).first()
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    for key, value in instance.dict().items():
        setattr(db_instance, key, value)

    db.commit()
    db.refresh(db_instance)
    return db_instance


@router.delete("/{instance_id}")
def delete_instance(instance_id: int, db: Session = Depends(get_db)):
    """Delete a GitLab instance"""
    instance = db.query(GitLabInstance).filter(
        GitLabInstance.id == instance_id
    ).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    db.delete(instance)
    db.commit()
    return {"message": "Instance deleted successfully"}
