from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PatientCreate(BaseModel):
    full_name: str
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    phone: Optional[str] = None
    language_preference: str = "hi"
    emergency_contact: dict = Field(default_factory=dict)


class PatientResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    internal_mrn: str
    full_name: str
    date_of_birth: Optional[date]
    gender: Optional[str]
    phone: Optional[str]
    language_preference: str
    abha_verified: bool
    created_at: datetime
    version: int


class PatientSearch(BaseModel):
    query: str
    tenant_id: UUID
    facility_id: Optional[UUID] = None
