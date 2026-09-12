from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.llm.schemas import EvidenceLink
from app.schemas.reviewed_document import TimelineEntryResponse
from app.summary_workflow.contracts import SummaryContent


class PatientDocumentInitiateRequest(BaseModel):
    facility_id: UUID
    encounter_id: UUID
    consent_reference: str = Field(min_length=1, max_length=256)
    original_filename: str = Field(min_length=1, max_length=255)
    declared_mime: str
    declared_size_bytes: int = Field(gt=0, le=10 * 1024 * 1024)


class PatientConsentCreate(BaseModel):
    encounter_id: UUID
    document_upload: bool = True
    retain_audio: bool = False
    expires_in_hours: int = Field(default=24, ge=1, le=168)


class PatientConsentResponse(BaseModel):
    id: UUID
    patient_id: UUID
    encounter_id: UUID
    purpose: str
    scope: dict[str, object]
    status: str
    granted_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    version: int


class PatientIntakeSubmissionCreate(BaseModel):
    facility_id: UUID
    encounter_id: UUID
    session_id: UUID
    consent_id: UUID
    language: Literal["hi", "en"]
    chief_complaint: str = Field(min_length=1, max_length=500)
    confirmed_answers: dict[str, str] = Field(default_factory=dict)
    summary_draft: SummaryContent
    decision: Literal["accepted", "rejected"]
    provider: Literal["mock", "template-fallback"]


class PatientIntakeSubmissionResponse(BaseModel):
    id: UUID
    patient_id: UUID
    encounter_id: UUID
    session_id: UUID
    consent_id: UUID
    decision: Literal["accepted", "rejected"]
    provider: Literal["mock", "template-fallback"]
    created_at: datetime


class PatientReportListItem(BaseModel):
    id: UUID
    encounter_id: UUID
    facility_id: UUID
    title: str
    signed_at: datetime
    signature_sha256: str
    provider: str
    degraded: bool


class PatientReportDetail(PatientReportListItem):
    generation: int = Field(ge=1)
    content: SummaryContent
    evidence: list[EvidenceLink]
    schema_version: str


class PatientDashboardResponse(BaseModel):
    patient_id: UUID
    signed_report_count: int = Field(ge=0)
    reviewed_timeline_count: int = Field(ge=0)
    recent_reports: list[PatientReportListItem]
    recent_timeline: list[TimelineEntryResponse]
