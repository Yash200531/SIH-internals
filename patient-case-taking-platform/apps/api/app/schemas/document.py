"""Public contracts for Phase 7 document registration."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.documents.registry import DocumentState


class DocumentInitiateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    purpose: Literal["treatment"]
    consent_reference: str = Field(min_length=1, max_length=256)
    original_filename: str = Field(min_length=1, max_length=255)
    declared_document_class: Literal["prescription"]
    declared_mime: Literal["application/pdf", "image/png", "image/jpeg", "image/webp"]
    declared_size_bytes: int = Field(gt=0, le=10 * 1024 * 1024)


class DocumentResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    purpose: str
    declared_document_class: str
    suggested_document_class: str | None
    reviewed_document_class: str | None
    declared_mime: str
    declared_size_bytes: int
    state: DocumentState
    version: int
    created_at: datetime
    updated_at: datetime
    upload_expires_at: datetime


class DocumentUploadGrantResponse(BaseModel):
    url: str
    expires_in_seconds: int
    required_headers: dict[str, str]


class DocumentFinalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(gt=0)


class DocumentVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(gt=0)
