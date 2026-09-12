"""Versioned OCR artifact envelope and provenance tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.documents.ocr_artifact import DocumentOcrArtifact
from app.ocr.base import OCRRegion, OCRResult


def _result() -> OCRResult:
    return OCRResult(
        text="Rx Metformin 500 mg",
        regions=[
            OCRRegion(
                text="Rx Metformin 500 mg",
                confidence=None,
                bbox=(1, 2, 90, 20),
                polygon=((1, 2), (90, 2), (90, 20), (1, 20)),
                language="en",
                script="Latn",
                reading_order=1,
            )
        ],
        confidence=None,
        provider="mock",
        model_version="mock-ocr-v1",
        language_pack_version="synthetic-en-v1",
        duration_ms=4,
    )


def test_artifact_retains_source_page_region_and_provider_provenance() -> None:
    tenant_id = uuid4()
    document_id = uuid4()
    page_artifact_id = uuid4()
    run_id = uuid4()

    artifact = DocumentOcrArtifact.from_result(
        tenant_id=tenant_id,
        document_id=document_id,
        page_artifact_id=page_artifact_id,
        ocr_run_id=run_id,
        page_number=1,
        width=100,
        height=40,
        source_checksum_sha256="a" * 64,
        page_checksum_sha256="b" * 64,
        preprocessing_version="normalize.v1",
        result=_result(),
    )

    assert artifact.schema_version == "DocumentOcrArtifact.v1"
    assert artifact.tenant_id == tenant_id
    assert artifact.document_id == document_id
    assert artifact.page_artifact_id == page_artifact_id
    assert artifact.ocr_run_id == run_id
    assert artifact.provider == "mock"
    assert artifact.model_version == "mock-ocr-v1"
    assert artifact.regions[0].provider_score is None
    assert artifact.regions[0].bbox == (1, 2, 90, 20)
    assert artifact.regions[0].reading_order == 1
    assert artifact.review_required is True


def test_artifact_identity_is_deterministic_for_idempotent_replay() -> None:
    values = {
        "tenant_id": uuid4(),
        "document_id": uuid4(),
        "page_artifact_id": uuid4(),
        "ocr_run_id": uuid4(),
        "page_number": 1,
        "width": 100,
        "height": 40,
        "source_checksum_sha256": "a" * 64,
        "page_checksum_sha256": "b" * 64,
        "preprocessing_version": "normalize.v1",
        "result": _result(),
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }

    first = DocumentOcrArtifact.from_result(**values)
    replay = DocumentOcrArtifact.from_result(**values)

    assert replay.artifact_id == first.artifact_id
    assert replay.model_dump(mode="json") == first.model_dump(mode="json")


def test_artifact_rejects_region_outside_page_bounds() -> None:
    result = _result()
    result.regions[0].bbox = (1, 2, 101, 20)

    with pytest.raises(ValidationError, match="page bounds"):
        DocumentOcrArtifact.from_result(
            tenant_id=uuid4(),
            document_id=uuid4(),
            page_artifact_id=uuid4(),
            ocr_run_id=uuid4(),
            page_number=1,
            width=100,
            height=40,
            source_checksum_sha256="a" * 64,
            page_checksum_sha256="b" * 64,
            preprocessing_version="normalize.v1",
            result=result,
        )
