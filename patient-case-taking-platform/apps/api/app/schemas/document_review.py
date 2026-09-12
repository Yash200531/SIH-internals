"""Public contracts for source-adjacent document review."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.documents.review import ReviewAction, ReviewState


class ReviewQueueItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    document_class: str
    state: str
    version: int
    updated_at: datetime
    candidate_count: int
    unresolved_count: int


class ReviewCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    candidate_id: UUID
    entity_type: str
    normalized_value: str | None
    unit: str | None
    source_page_artifact_id: UUID
    source_ocr_artifact_id: UUID | None
    source_region_id: UUID | None
    source_page_number: int
    parser_signal: str
    negated: bool
    temporality: str
    subject: str
    uncertainty: str | None
    document_statement: bool
    clinician_confirmed_current: bool
    review_state: ReviewState
    version: int
    source_page_width: int | None
    source_page_height: int | None
    source_bbox: tuple[int, int, int, int] | None
    source_polygon: tuple[tuple[int, int], ...] | None


class ReviewDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    purpose: str
    document_class: str
    state: str
    version: int
    updated_at: datetime
    candidates: tuple[ReviewCandidateResponse, ...]
    pages: tuple["ReviewPageResponse", ...]


class ReviewPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    page_number: int
    width: int
    height: int
    preprocessing_version: str


class CandidateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ReviewAction
    expected_candidate_version: int = Field(gt=0)
    corrected_value: str | None = Field(default=None, max_length=512)
    corrected_unit: str | None = Field(default=None, max_length=32)
    reason_code: str | None = Field(default=None, max_length=64)
    source_verified: bool = False


class ReviewFinalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_document_version: int = Field(gt=0)


class OpenManualReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_document_version: int = Field(gt=0)


class ManualCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(min_length=1, max_length=64)
    normalized_value: str = Field(min_length=1, max_length=2_000)
    unit: str | None = Field(default=None, max_length=32)
    source_page_artifact_id: UUID
    source_page_number: int = Field(gt=0)
    source_verified: bool


class PagePreviewResponse(BaseModel):
    url: str
    expires_in_seconds: int
