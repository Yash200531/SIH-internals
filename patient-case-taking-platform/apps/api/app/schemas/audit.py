from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    tenant_id: UUID
    facility_id: Optional[UUID] = None
    actor_id: Optional[UUID] = None
    actor_type: str
    actor_role: Optional[str] = None
    action: str
    resource_type: str
    resource_id: Optional[UUID] = None
    purpose: Optional[str] = None
    outcome: str = "success"
    outcome_detail: Optional[str] = None
    audit_metadata: dict = Field(default_factory=dict)


class AuditEventResponse(BaseModel):
    id: UUID
    action: str
    resource_type: str
    outcome: str
    created_at: datetime
