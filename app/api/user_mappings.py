"""User mapping management endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from datetime import datetime

from app.models.base import get_db
from app.models import UserMapping

router = APIRouter(prefix="/api/user-mappings", tags=["user-mappings"])


class UserMappingCreate(BaseModel):
    source_instance_id: int
    source_username: str
    target_instance_id: int
    target_username: str


class UserMappingResponse(BaseModel):
    id: int
    source_instance_id: int
    source_username: str
    target_instance_id: int
    target_username: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/", response_model=List[UserMappingResponse])
def list_user_mappings(db: Session = Depends(get_db)):
    """List all user mappings"""
    mappings = db.query(UserMapping).all()
    return mappings


@router.post("/", response_model=UserMappingResponse)
def create_user_mapping(mapping: UserMappingCreate, db: Session = Depends(get_db)):
    """Create a new user mapping"""
    # Check if mapping already exists
    existing = db.query(UserMapping).filter(
        UserMapping.source_instance_id == mapping.source_instance_id,
        UserMapping.source_username == mapping.source_username,
        UserMapping.target_instance_id == mapping.target_instance_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="User mapping already exists")

    db_mapping = UserMapping(**mapping.dict())
    db.add(db_mapping)
    db.commit()
    db.refresh(db_mapping)
    return db_mapping


@router.get("/{mapping_id}", response_model=UserMappingResponse)
def get_user_mapping(mapping_id: int, db: Session = Depends(get_db)):
    """Get a specific user mapping"""
    mapping = db.query(UserMapping).filter(UserMapping.id == mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="User mapping not found")
    return mapping


@router.delete("/{mapping_id}")
def delete_user_mapping(mapping_id: int, db: Session = Depends(get_db)):
    """Delete a user mapping"""
    mapping = db.query(UserMapping).filter(UserMapping.id == mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="User mapping not found")

    db.delete(mapping)
    db.commit()
    return {"message": "User mapping deleted successfully"}
