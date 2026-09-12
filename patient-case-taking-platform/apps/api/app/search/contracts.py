"""Typed records and responses for the clinical search projection."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class SourceKind(StrEnum):
    SIGNED_SUMMARY = "signed_summary"
    REVIEWED_FACT = "reviewed_fact"


class ClinicalSearchRecord(BaseModel):
    """Internal projection document; tenant scope is never returned directly."""

    record_id: str = Field(min_length=3, max_length=96)
    tenant_id: UUID
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    document_id: UUID | None = None
    source_kind: SourceKind
    source_id: UUID
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=50_000)
    entity_type: str | None = Field(default=None, max_length=128)
    statement_status: str | None = Field(default=None, max_length=64)
    occurred_at: datetime
    security_labels: list[str] = Field(min_length=1, max_length=16)

    @field_validator("title", "content")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("searchable text cannot be blank")
        return normalized

    @field_validator("security_labels")
    @classmethod
    def normalize_labels(cls, labels: list[str]) -> list[str]:
        normalized = sorted({label.strip().lower() for label in labels if label.strip()})
        if not normalized:
            raise ValueError("at least one security label is required")
        return normalized

    @model_validator(mode="after")
    def require_human_review_label(self) -> Self:
        if "human-reviewed" not in self.security_labels:
            raise ValueError("clinical search records must be human reviewed")
        return self


class ClinicalSearchQuery(BaseModel):
    """Authorized criteria passed to a search adapter."""

    tenant_id: UUID
    patient_id: UUID
    facility_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    q: str | None = Field(default=None, max_length=200)
    source_kind: SourceKind | None = None
    entity_type: str | None = Field(default=None, max_length=128)
    from_date: datetime | None = None
    to_date: datetime | None = None
    page_size: int = Field(default=20, ge=1, le=50)
    cursor: str | None = Field(default=None, max_length=1024)

    @field_validator("facility_ids")
    @classmethod
    def normalize_facilities(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return tuple(sorted(set(values), key=str))

    @field_validator("q", "entity_type")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @model_validator(mode="after")
    def validate_date_window(self) -> Self:
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class SearchHighlight(BaseModel):
    field: Annotated[str, Field(pattern="^(title|content)$")]
    fragments: list[str] = Field(max_length=2)


class ClinicalSearchHit(BaseModel):
    record_id: str
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    document_id: UUID | None = None
    source_kind: SourceKind
    source_id: UUID
    title: str
    entity_type: str | None = None
    statement_status: str | None = None
    occurred_at: datetime
    highlights: list[SearchHighlight] = Field(default_factory=list, max_length=2)


class SearchFacets(BaseModel):
    source_kinds: dict[str, int] = Field(default_factory=dict)
    entity_types: dict[str, int] = Field(default_factory=dict)


class ClinicalSearchResponse(BaseModel):
    total: int = Field(ge=0)
    hits: list[ClinicalSearchHit]
    facets: SearchFacets
    took_ms: int = Field(ge=0)
    next_cursor: str | None = None
