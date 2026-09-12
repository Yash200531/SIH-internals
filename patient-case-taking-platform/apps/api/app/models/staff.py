from typing import Optional
from uuid import UUID

from pydantic import Field

from app.models.base import BaseRecord


class Staff(BaseRecord):
    __tablename__ = "staff"
    tenant_id: UUID
    facility_id: UUID
    clerk_user_id: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    full_name: str
    role: str  # "doctor", "nurse", "receptionist", "admin", "kiosk_operator"
    departments: list[UUID] = Field(default_factory=list)
    is_active: bool = True
    hpr_id: Optional[str] = None
    hfr_id: Optional[str] = None
