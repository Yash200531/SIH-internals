"""Frozen synthetic prescription extraction fixtures."""

from datetime import UTC, datetime
from uuid import uuid4

from app.documents.extraction import PrescriptionRulesExtractor
from app.documents.ocr_artifact import DocumentOcrArtifact
from app.ocr.base import OCRRegion, OCRResult


def _artifact(*lines: str) -> DocumentOcrArtifact:
    regions = [
        OCRRegion(
            text=line,
            confidence=0.9,
            bbox=(1, index * 20, 500, index * 20 + 15),
            language="en",
            script="Latn",
            reading_order=index,
        )
        for index, line in enumerate(lines, start=1)
    ]
    return DocumentOcrArtifact.from_result(
        tenant_id=uuid4(),
        document_id=uuid4(),
        page_artifact_id=uuid4(),
        ocr_run_id=uuid4(),
        page_number=1,
        width=600,
        height=max(100, (len(lines) + 1) * 20),
        source_checksum_sha256="a" * 64,
        page_checksum_sha256="b" * 64,
        preprocessing_version="normalize.v1",
        result=OCRResult(
            text="\n".join(lines),
            regions=regions,
            confidence=0.9,
            provider="fixture",
            model_version="fixture-v1",
            language_pack_version="fixture-en-v1",
            duration_ms=1,
        ),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _by_type(draft) -> dict[str, list]:
    result: dict[str, list] = {}
    for candidate in draft.candidates:
        result.setdefault(candidate.entity_type, []).append(candidate)
    return result


def test_extracts_narrow_prescription_fields_with_region_provenance() -> None:
    artifact = _artifact(
        "Date: 02/09/2026",
        "Rx Tab Metformin 500 mg PO BID for 30 days after food",
    )

    draft = PrescriptionRulesExtractor().extract([artifact])
    fields = _by_type(draft)

    assert fields["document_date"][0].normalized_value == "2026-09-02"
    assert fields["medication_statement"][0].normalized_value == "Metformin"
    assert fields["strength"][0].normalized_value == "500"
    assert fields["strength"][0].unit == "mg"
    assert fields["route"][0].normalized_value == "oral"
    assert fields["frequency"][0].normalized_value == "twice_daily"
    assert fields["duration"][0].normalized_value == "P30D"
    assert fields["instructions"][0].normalized_value == "after food"
    for candidate in draft.candidates:
        assert candidate.source.document_id == artifact.document_id
        assert candidate.source.page_artifact_id == artifact.page_artifact_id
        assert candidate.source.ocr_artifact_id == artifact.artifact_id
        assert candidate.source.region_id in {
            region.region_id for region in artifact.regions
        }
        assert candidate.source.page_width == artifact.width
        assert candidate.source.page_height == artifact.height
        assert candidate.source.bbox is not None
        assert candidate.document_statement is True
        assert candidate.review_state == "unreviewed"
        assert candidate.model_signal is None


def test_negation_history_and_other_subject_are_explicit_not_inferred_current() -> None:
    artifact = _artifact("Mother previously stopped Tab Aspirin 75 mg OD")

    draft = PrescriptionRulesExtractor().extract([artifact])
    medication = _by_type(draft)["medication_statement"][0]

    assert medication.normalized_value == "Aspirin"
    assert medication.negated is True
    assert medication.temporality == "historical"
    assert medication.subject == "other"
    assert medication.clinician_confirmed_current is False


def test_ambiguous_eye_abbreviation_abstains_from_frequency_normalization() -> None:
    artifact = _artifact("Eye drops Timolol 0.5% OD")

    draft = PrescriptionRulesExtractor().extract([artifact])
    fields = _by_type(draft)

    assert "frequency" not in fields
    assert fields["strength"][0].normalized_value == "0.5"
    assert fields["strength"][0].unit == "%"
    assert "ambiguous_abbreviation:OD" in draft.warnings


def test_unsupported_diagnosis_assertion_is_not_emitted_as_candidate() -> None:
    artifact = _artifact("Diagnosis: Diabetes mellitus type 2")

    draft = PrescriptionRulesExtractor().extract([artifact])

    assert draft.candidates == ()
    assert "unsupported_assertion:diagnosis" in draft.warnings


def test_decimal_comma_strength_is_normalized_without_unit_inference() -> None:
    artifact = _artifact("Cap Cholecalciferol 0,5 mg once daily")

    draft = PrescriptionRulesExtractor().extract([artifact])
    strength = _by_type(draft)["strength"][0]

    assert strength.normalized_value == "0.5"
    assert strength.unit == "mg"


def test_missing_route_duration_and_instruction_are_not_invented() -> None:
    artifact = _artifact("Tab Paracetamol 500 mg")

    draft = PrescriptionRulesExtractor().extract([artifact])
    fields = _by_type(draft)

    assert set(fields) == {"medication_statement", "strength"}


def test_unprefixed_name_strength_stays_uncertain_and_instruction_is_not_a_drug():
    artifact = _artifact("METFORMIN 500 MG", "TAKE ONE TABLET DAILY")
    draft = PrescriptionRulesExtractor().extract([artifact])
    fields = _by_type(draft)
    assert [item.normalized_value for item in fields["medication_statement"]] == ["METFORMIN"]
    assert fields["strength"][0].normalized_value == "500"
    assert fields["medication_statement"][0].uncertainty == "medication_name_requires_verification"
    assert "standalone_instruction_requires_review" in draft.warnings
    assert fields["medication_statement"][0].source.region_id == artifact.regions[0].region_id
