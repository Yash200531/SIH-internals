from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ConsentCreate(BaseModel):
    patient_id: UUID
    encounter_id: Optional[UUID] = None
    purpose: str
    scope: dict = Field(default_factory=dict)
    granted_by: str = "patient"
    expires_at: Optional[datetime] = None


class ConsentResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    patient_id: UUID
    purpose: str
    scope: dict
    status: str
    granted_at: datetime
    expires_at: Optional[datetime]
    version: int


class ConsentRevoke(BaseModel):
    reason: str
