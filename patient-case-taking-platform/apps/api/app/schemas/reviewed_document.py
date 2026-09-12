"""Public read and withdrawal contracts for reviewed document facts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReviewedFactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    encounter_id: UUID
    document_id: UUID
    candidate_id: UUID
    entity_type: str
    normalized_value: str
    unit: str | None
    source_page_artifact_id: UUID
    source_ocr_artifact_id: UUID | None
    source_region_id: UUID | None
    source_page_number: int
    document_statement: bool
    clinician_confirmed_current: bool
    active: bool
    promoted_at: datetime
    withdrawn_at: datetime | None
    withdrawal_reason_code: str | None


class TimelineEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    encounter_id: UUID
    document_id: UUID
    fact_id: UUID
    event_type: str
    display_value: str
    unit: str | None
    statement_status: str
    occurred_at: datetime


class WithdrawalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1, max_length=64)


class WithdrawalResponse(BaseModel):
    document_id: UUID
    withdrawn_fact_count: int
