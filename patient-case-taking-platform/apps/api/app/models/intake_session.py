from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import Field

from app.models.base import BaseRecord


class IntakeSession(BaseRecord):
    __tablename__ = "intake_session"
    tenant_id: UUID
    facility_id: UUID
    encounter_id: Optional[UUID] = None
    patient_id: Optional[UUID] = None
    session_type: str = "kiosk"
    device_id: Optional[str] = None
    status: str = "active"
    language: str = "hi"
    expires_at: datetime
    last_activity_at: datetime
    wiped_at: Optional[datetime] = None
    metadata: dict = Field(default_factory=dict)
