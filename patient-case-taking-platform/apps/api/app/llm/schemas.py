"""Versioned request and response contracts for Phase 5 clinical AI tasks."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Language = Literal["hi", "en"]
AnswerType = Literal["free_text", "single_choice", "number", "review", "urgent_action"]
ClinicalProvider = Literal["mock", "template-fallback", "medgemma", "anthropic"]


class OutputConfidence(BaseModel):
    """Technical quality signal, never a probability that a diagnosis is correct."""

    score: float = Field(ge=0.0, le=1.0)
    basis: Literal["deterministic_rule", "structured_completeness", "template_fallback"]
    not_clinical_probability: Literal[True] = True


class EvidenceLink(BaseModel):
    """Pointer to a source field without copying its potentially sensitive value."""

    output_path: str = Field(min_length=1, max_length=160)
    source_path: str = Field(min_length=1, max_length=160)
    source_type: Literal["patient_response", "document", "deterministic_rule", "clinician_edit"]


class DialogueRequest(BaseModel):
    tenant_id: UUID
    session_id: UUID
    language: Language = "hi"
    chief_complaint: str = Field(min_length=1, max_length=500)
    last_patient_message: str = Field(default="", max_length=2_000)
    collected_answers: dict[str, Any] = Field(default_factory=dict)
    include_ayush: bool = False

    @field_validator("collected_answers")
    @classmethod
    def limit_collected_answers(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 100:
            raise ValueError("collected_answers cannot contain more than 100 fields")
        return value


class DialogueResponse(BaseModel):
    question: str = Field(min_length=1, max_length=1_000)
    answer_type: AnswerType
    next_domain: str = Field(min_length=1, max_length=80)
    options: list[str] = Field(default_factory=list, max_length=10)
    safety_flags: list[str] = Field(default_factory=list, max_length=20)
    escalation_required: bool = False
    confidence: OutputConfidence
    evidence: list[EvidenceLink] = Field(default_factory=list, max_length=100)
    provider: ClinicalProvider
    schema_version: Literal["phase5.dialogue.v1"] = "phase5.dialogue.v1"
    degraded: bool = False


class ClinicalSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    encounter_id: UUID
    language: Language = "en"
    chief_complaint: str = Field(min_length=1, max_length=500)
    confirmed_answers: dict[str, Any] = Field(default_factory=dict)
    transcript: str = Field(default="", max_length=20_000)
    document_facts: list[str] = Field(default_factory=list, max_length=100)
    document_fact_source_paths: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("document_fact_source_paths")
    @classmethod
    def bound_source_paths(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 160 for item in value):
            raise ValueError("document fact source paths must contain 1 to 160 characters")
        return value


class ClinicalSummaryResponse(BaseModel):
    chief_complaint: str
    history_of_present_illness: list[str]
    relevant_negatives: list[str]
    document_facts: list[str]
    red_flags: list[str]
    uncertainties: list[str]
    confidence: OutputConfidence
    evidence: list[EvidenceLink] = Field(default_factory=list, max_length=200)
    clinician_review_required: Literal[True] = True
    provider: ClinicalProvider
    schema_version: Literal["phase5.summary.v1"] = "phase5.summary.v1"
    degraded: bool = False


class ProviderHealthResponse(BaseModel):
    provider: str
    ready: bool
    external_network_used: bool
