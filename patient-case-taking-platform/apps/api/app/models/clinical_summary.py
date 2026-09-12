from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import Field

from app.models.base import BaseRecord

SUMMARY_TYPES = ("encounter", "discharge", "referral")
SUMMARY_STATUSES = ("draft", "review", "signed", "archived")


class ClinicalSummary(BaseRecord):
    __tablename__ = "clinical_summary"
    patient_id: UUID
    encounter_id: UUID

    # Content
    summary_type: str = "encounter"
    content: dict = Field(default_factory=dict)  # {chief_complaint, history, vitals, assessment, plan}
    raw_text: Optional[str] = None

    # Lifecycle
    status: str = "draft"
    generated_by: str = "ai"  # "ai", "clinician", "hybrid"
    model_version: Optional[str] = None

    # Provenance
    source_answers: list = Field(default_factory=list)
    source_documents: list = Field(default_factory=list)

    # Clinician verification
    reviewed_by: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    clinician_edits: dict = Field(default_factory=dict)

    # Signing
    signed_by: Optional[UUID] = None
    signed_at: Optional[datetime] = None
    signature_hash: Optional[str] = None

    # Versioning
    previous_version_id: Optional[UUID] = None
