from datetime import UTC, datetime
from typing import Optional
from uuid import UUID

from pydantic import Field

from app.models.base import BaseRecord

CONSENT_STATUSES = ("granted", "expired", "revoked", "denied")


class ConsentArtifact(BaseRecord):
    __tablename__ = "consent_artifact"
    patient_id: UUID
    encounter_id: Optional[UUID] = None

    # Consent scope
    purpose: str  # "treatment", "research", "abdm_share", "emergency"
    scope: dict = Field(default_factory=dict)  # {"categories": [...], "recipients": [...]}

    # Lifecycle
    status: str = "granted"
    granted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revoke_reason: Optional[str] = None

    # Delegation
    granted_by: str = "patient"  # "patient", "caregiver", "legal_guardian"
    grantee_id: Optional[UUID] = None

    # ABDM consent exchange
    abdm_consent_id: Optional[str] = None
    abdm_status: Optional[str] = None

    # Audit
    receipt_object_key: Optional[str] = None
    previous_version_id: Optional[UUID] = None
