from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import Field

from app.models.base import BaseRecord

ENCOUNTER_STATES = ("intake", "in_progress", "draft", "signed", "archived")
VALID_TRANSITIONS = {
    "intake": ("in_progress",),
    "in_progress": ("draft",),
    "draft": ("signed",),
    "signed": ("archived",),
    "archived": (),
}


class Encounter(BaseRecord):
    __tablename__ = "encounter"
    tenant_id: UUID
    facility_id: UUID
    patient_id: UUID
    department_id: Optional[UUID] = None
    assigned_staff_id: Optional[UUID] = None
    status: str = "intake"
    encounter_type: str = "outpatient"
    chief_complaint: Optional[str] = None
    started_at: Optional[datetime] = None
    draft_at: Optional[datetime] = None
    signed_at: Optional[datetime] = None
    signed_by: Optional[UUID] = None
    metadata: dict = Field(default_factory=dict)
