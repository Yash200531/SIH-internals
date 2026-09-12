from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import Field

from app.models.base import BaseRecord


class PatientProfile(BaseRecord):
    __tablename__ = "patient_profile"
    tenant_id: UUID
    internal_mrn: str
    full_name: str
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: dict = Field(default_factory=dict)
    language_preference: str = "hi"
    is_active: bool = True
    abha_number: Optional[str] = None
    abha_address: Optional[str] = None
    abha_verified: bool = False
    abha_linked_at: Optional[datetime] = None
    emergency_contact: dict = Field(default_factory=dict)
