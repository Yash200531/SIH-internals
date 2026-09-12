from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class IntakeSessionCreate(BaseModel):
    facility_id: UUID
    session_type: str = "kiosk"
    device_id: Optional[str] = None
    language: str = "hi"


class IntakeSessionResponse(BaseModel):
    id: UUID
    facility_id: UUID
    session_type: str
    status: str
    language: str
    expires_at: datetime
    created_at: datetime
