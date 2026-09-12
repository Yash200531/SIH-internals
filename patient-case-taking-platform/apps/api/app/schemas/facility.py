from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class FacilityCreate(BaseModel):
    name: str
    slug: str
    address: dict = Field(default_factory=dict)
    phone: Optional[str] = None


class FacilityResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime
