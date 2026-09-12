from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class EncounterCreate(BaseModel):
    patient_id: UUID
    facility_id: UUID
    department_id: Optional[UUID] = None
    encounter_type: str = "outpatient"
    chief_complaint: Optional[str] = None


class EncounterResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    patient_id: UUID
    facility_id: UUID
    status: str
    encounter_type: str
    chief_complaint: Optional[str]
    created_at: datetime
    version: int


class EncounterStatusUpdate(BaseModel):
    status: str
