"""Versioned contracts for the Phase 8 clinical summary lifecycle."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.llm.schemas import EvidenceLink, OutputConfidence


class SummaryStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    REJECTED = "rejected"
    SIGNED = "signed"
    SUPERSEDED = "superseded"


class SummaryContent(BaseModel):
    """Clinician-visible content. It is PHI and must not enter metadata logs."""

    chief_complaint: str = Field(min_length=1, max_length=500)
    history_of_present_illness: list[str] = Field(min_length=1, max_length=100)
    relevant_negatives: list[str] = Field(default_factory=list, max_length=100)
    document_facts: list[str] = Field(default_factory=list, max_length=100)
    red_flags: list[str] = Field(default_factory=list, max_length=50)
    uncertainties: list[str] = Field(default_factory=list, max_length=100)

    @field_validator(
        "history_of_present_illness",
        "relevant_negatives",
        "document_facts",
        "red_flags",
        "uncertainties",
    )
    @classmethod
    def bound_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 1_000 for item in value):
            raise ValueError("summary items must contain 1 to 1000 characters")
        return value


class SummarySourceBundle(BaseModel):
    """Server-assembled, confirmed evidence accepted by the generation boundary."""

    tenant_id: UUID
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    language: Literal["hi", "en"] = "en"
    chief_complaint: str = Field(min_length=1, max_length=500)
    confirmed_answers: dict[str, Any] = Field(default_factory=dict)
    reviewed_document_facts: list[str] = Field(default_factory=list, max_length=100)
    reviewed_document_fact_ids: list[UUID] = Field(default_factory=list, max_length=100)
    deterministic_red_flags: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("confirmed_answers")
    @classmethod
    def bound_answers(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 100:
            raise ValueError("confirmed_answers cannot contain more than 100 fields")
        return value


class ConfirmedEncounterContext(BaseModel):
    tenant_id: UUID
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    language: Literal["hi", "en"] = "en"
    chief_complaint: str = Field(min_length=1, max_length=500)
    confirmed_answers: dict[str, Any] = Field(default_factory=dict)
    deterministic_red_flags: list[str] = Field(default_factory=list, max_length=50)
    confirmed_by_actor_id: UUID
    confirmed_at: datetime
    version: int = Field(ge=1)


class ConfirmEncounterContextCommand(BaseModel):
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    language: Literal["hi", "en"] = "en"
    chief_complaint: str = Field(min_length=1, max_length=500)
    confirmed_answers: dict[str, Any] = Field(default_factory=dict)
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("confirmed_answers")
    @classmethod
    def bound_context_answers(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 100:
            raise ValueError("confirmed_answers cannot contain more than 100 fields")
        return value


class SummaryRecord(BaseModel):
    id: UUID
    tenant_id: UUID
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    lineage_id: UUID
    generation: int = Field(ge=1)
    parent_summary_id: UUID | None = None
    status: SummaryStatus
    content: SummaryContent
    evidence: list[EvidenceLink] = Field(default_factory=list, max_length=250)
    confidence: OutputConfidence
    provider: Literal["mock", "template-fallback", "medgemma", "anthropic"]
    schema_version: Literal["phase8.summary-workflow.v1"] = "phase8.summary-workflow.v1"
    degraded: bool = False
    lock_version: int = Field(ge=1)
    created_by_actor_id: UUID
    created_at: datetime
    updated_at: datetime
    signed_by_actor_id: UUID | None = None
    signed_at: datetime | None = None
    signature_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    rejection_reason: str | None = Field(default=None, max_length=500)
    request_hash_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", exclude=True)


class SummaryAction(BaseModel):
    id: UUID
    tenant_id: UUID
    summary_id: UUID
    actor_id: UUID
    actor_role: Literal["doctor", "nurse", "system"]
    action: Literal["generated", "edited", "submitted", "rejected", "regenerated", "signed"]
    from_status: SummaryStatus | None
    to_status: SummaryStatus
    resulting_lock_version: int = Field(ge=1)
    occurred_at: datetime
    metadata: dict[str, str | int | bool | None] = Field(default_factory=dict)


class EditSummaryCommand(BaseModel):
    expected_version: int = Field(ge=1)
    content: SummaryContent


class VersionCommand(BaseModel):
    expected_version: int = Field(ge=1)


class RejectSummaryCommand(VersionCommand):
    reason: str = Field(min_length=1, max_length=500)


class GenerateSummaryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    language: Literal["hi", "en"] = "en"


class RegenerateSummaryCommand(GenerateSummaryCommand):
    expected_version: int = Field(ge=1)
