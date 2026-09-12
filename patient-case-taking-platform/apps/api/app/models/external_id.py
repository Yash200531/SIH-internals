from datetime import datetime
from typing import Optional
from uuid import UUID

from app.models.base import BaseRecord


class ExternalId(BaseRecord):
    __tablename__ = "external_id"
    patient_id: UUID
    id_type: str
    id_value: str
    is_verified: bool = False
    verified_at: Optional[datetime] = None
    tenant_id: UUID
