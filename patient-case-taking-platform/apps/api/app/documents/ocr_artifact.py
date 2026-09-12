"""Protected, versioned OCR artifacts with source-region provenance."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ocr.base import OCRResult


class OcrArtifactRegion(BaseModel):
    model_config = ConfigDict(frozen=True)

    region_id: UUID
    text: str = Field(min_length=1, max_length=20_000)
    provider_score: float | None = Field(default=None, ge=0, le=1)
    bbox: tuple[int, int, int, int] | None = None
    polygon: tuple[tuple[int, int], ...] | None = None
    language: str | None = Field(default=None, max_length=32)
    script: str | None = Field(default=None, max_length=32)
    reading_order: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_geometry(self) -> "OcrArtifactRegion":
        if self.bbox is not None:
            x1, y1, x2, y2 = self.bbox
            if min(self.bbox) < 0 or x2 <= x1 or y2 <= y1:
                raise ValueError("OCR region bounding box is invalid")
        if self.polygon is not None:
            if len(self.polygon) < 3 or any(min(point) < 0 for point in self.polygon):
                raise ValueError("OCR region polygon is invalid")
        return self


class DocumentOcrArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["DocumentOcrArtifact.v1"] = "DocumentOcrArtifact.v1"
    artifact_id: UUID
    tenant_id: UUID
    document_id: UUID
    page_artifact_id: UUID
    ocr_run_id: UUID
    page_number: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    source_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preprocessing_version: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=64)
    model_version: str = Field(min_length=1, max_length=128)
    language_pack_version: str = Field(min_length=1, max_length=128)
    provider_score: float | None = Field(default=None, ge=0, le=1)
    normalized_text: str = Field(max_length=2_000_000)
    regions: tuple[OcrArtifactRegion, ...]
    quality_signals: dict[str, float | bool | None] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    duration_ms: int = Field(ge=0)
    review_required: Literal[True] = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_region_provenance(self) -> "DocumentOcrArtifact":
        reading_order = [region.reading_order for region in self.regions]
        if reading_order != list(range(1, len(self.regions) + 1)):
            raise ValueError("OCR region reading order must be contiguous")
        for region in self.regions:
            if region.bbox is not None:
                _x1, _y1, x2, y2 = region.bbox
                if x2 > self.width or y2 > self.height:
                    raise ValueError("OCR region bounding box exceeds page bounds")
            if region.polygon is not None and any(
                x > self.width or y > self.height for x, y in region.polygon
            ):
                raise ValueError("OCR region polygon exceeds page bounds")
        return self

    @classmethod
    def from_result(
        cls,
        *,
        tenant_id: UUID,
        document_id: UUID,
        page_artifact_id: UUID,
        ocr_run_id: UUID,
        page_number: int,
        width: int,
        height: int,
        source_checksum_sha256: str,
        page_checksum_sha256: str,
        preprocessing_version: str,
        result: OCRResult,
        quality_signals: dict[str, float | bool | None] | None = None,
        created_at: datetime | None = None,
    ) -> "DocumentOcrArtifact":
        artifact_id = uuid5(ocr_run_id, str(page_artifact_id))
        regions = tuple(
            OcrArtifactRegion(
                region_id=uuid5(artifact_id, f"region:{index}"),
                text=region.text,
                provider_score=region.confidence,
                bbox=region.bbox,
                polygon=region.polygon,
                language=region.language,
                script=region.script,
                reading_order=index,
            )
            for index, region in enumerate(result.regions, start=1)
        )
        return cls(
            artifact_id=artifact_id,
            tenant_id=tenant_id,
            document_id=document_id,
            page_artifact_id=page_artifact_id,
            ocr_run_id=ocr_run_id,
            page_number=page_number,
            width=width,
            height=height,
            source_checksum_sha256=source_checksum_sha256,
            page_checksum_sha256=page_checksum_sha256,
            preprocessing_version=preprocessing_version,
            provider=result.provider,
            model_version=result.model_version,
            language_pack_version=result.language_pack_version,
            provider_score=result.confidence,
            normalized_text=result.text,
            regions=regions,
            quality_signals=quality_signals or {},
            warnings=result.warnings,
            duration_ms=result.duration_ms,
            created_at=created_at or datetime.now(UTC),
        )
