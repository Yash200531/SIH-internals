from typing import Optional
from uuid import UUID

from pydantic import Field

from app.models.base import BaseRecord


class Facility(BaseRecord):
    __tablename__ = "facility"
    tenant_id: UUID
    name: str
    slug: str
    address: dict = Field(default_factory=dict)
    phone: Optional[str] = None
    is_active: bool = True
    settings: dict = Field(default_factory=dict)
