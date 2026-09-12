from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SummaryCreate(BaseModel):
    patient_id: UUID
    encounter_id: UUID
    summary_type: str = "encounter"
    content: dict
    raw_text: Optional[str] = None
    generated_by: str = "ai"
    model_version: Optional[str] = None
    source_answers: list = Field(default_factory=list)
    source_documents: list = Field(default_factory=list)


class SummaryResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    encounter_id: UUID
    summary_type: str
    content: dict
    status: str
    generated_by: str
    version: int
    created_at: datetime


class SummarySign(BaseModel):
    signed_by: UUID
    clinician_edits: dict = Field(default_factory=dict)
