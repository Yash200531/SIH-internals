from typing import Optional
from uuid import UUID

from pydantic import Field

from app.models.base import BaseRecord


class AuditLog(BaseRecord):
    __tablename__ = "audit_log"

    # Who
    actor_id: Optional[UUID] = None
    actor_type: str  # "staff", "patient", "system", "kiosk"
    actor_role: Optional[str] = None

    # What
    action: str  # "create", "read", "update", "delete", "sign", "export", "consent_grant", "consent_revoke", "break_glass"
    resource_type: str  # "patient", "encounter", "consent", "document", "note"
    resource_id: Optional[UUID] = None

    # Why
    purpose: Optional[str] = None

    # Outcome
    outcome: str = "success"
    outcome_detail: Optional[str] = None

    # Context
    facility_id: Optional[UUID] = None
    session_id: Optional[UUID] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    # PHI-safe metadata only
    audit_metadata: dict = Field(default_factory=dict)

    is_immutable: bool = True
