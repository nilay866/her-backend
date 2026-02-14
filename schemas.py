from pydantic import BaseModel
from typing import Optional
from datetime import date
from uuid import UUID

class HealthLogCreate(BaseModel):
    user_id: UUID
    log_type: str = "health_check"
    title: Optional[str] = "Health Log"
    log_date: Optional[date] = None
    description: Optional[str] = None
    pain_level: Optional[int] = None
    bleeding_level: Optional[str] = None
    mood: Optional[str] = None
    notes: Optional[str] = None

class HealthLogUpdate(BaseModel):
    log_type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    log_date: Optional[date] = None
    pain_level: Optional[int] = None
    bleeding_level: Optional[str] = None
    mood: Optional[str] = None
    notes: Optional[str] = None

class HealthLogResponse(BaseModel):
    id: UUID
    user_id: UUID
    log_type: str
    title: str
    description: Optional[str]
    log_date: date
    pain_level: Optional[int]
    bleeding_level: Optional[str]
    mood: Optional[str]
    notes: Optional[str]

    class Config:
        from_attributes = True
