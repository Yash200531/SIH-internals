"""Evaluate deterministic Phase 7 extraction on the frozen synthetic set."""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.documents.extraction import PrescriptionRulesExtractor
from app.documents.ocr_artifact import DocumentOcrArtifact
from app.ocr.base import OCRRegion, OCRResult


def _key(candidate: Any) -> tuple[object, ...]:
    return (
        candidate.entity_type,
        candidate.normalized_value,
        candidate.unit,
        candidate.negated,
        candidate.temporality,
        candidate.subject,
    )


def evaluate_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    tenant_id = uuid4()
    document_id = uuid4()
    page_id = uuid4()
    ocr_run_id = uuid4()
    regions = [
        OCRRegion(
            text=region["text"],
            confidence=1.0,
            bbox=tuple(region["bbox"]),
            language=fixture["language"],
            script=fixture["script"],
        )
        for region in fixture["ocr_regions"]
    ]
    artifact = DocumentOcrArtifact.from_result(
        tenant_id=tenant_id,
        document_id=document_id,
        page_artifact_id=page_id,
        ocr_run_id=ocr_run_id,
        page_number=1,
        width=1000,
        height=1400,
        source_checksum_sha256="a" * 64,
        page_checksum_sha256="b" * 64,
        preprocessing_version="synthetic-fixture.v1",
        result=OCRResult(
            text="\n".join(region["text"] for region in fixture["ocr_regions"]),
            regions=regions,
            confidence=1.0,
            provider="synthetic-fixture",
            model_version="fixture-v1",
            language_pack_version="fixture-multilingual-v1",
            duration_ms=0,
        ),
    )
    draft = PrescriptionRulesExtractor().extract([artifact])
    actual = sorted(_key(candidate) for candidate in draft.candidates)
    expected = sorted(tuple(value) for value in fixture["expected"])
    source_linked = all(
        candidate.source.document_id == document_id
        and candidate.source.page_artifact_id == page_id
        and candidate.source.ocr_artifact_id == artifact.artifact_id
        and candidate.source.region_id in {region.region_id for region in artifact.regions}
        and candidate.source.bbox is not None
        for candidate in draft.candidates
    )
    return {
        "fixture_id": fixture["fixture_id"],
        "exact_match": actual == expected,
        "source_linked": source_linked,
        "warning_exact_match": sorted(draft.warnings)
        == sorted(fixture["expected_warnings"]),
        "expected_count": len(expected),
        "actual_count": len(actual),
        "strata": {
            key: fixture[key]
            for key in (
                "document_class",
                "language",
                "script",
                "capture_source",
                "quality",
                "page_type",
            )
        },
    }


def evaluate_manifest(path: Path) -> dict[str, Any]:
    fixtures = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    results = [evaluate_fixture(fixture) for fixture in fixtures]
    subgroup: dict[str, dict[str, list[bool]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for result in results:
        for dimension, value in result["strata"].items():
            subgroup[dimension][str(value)].append(result["exact_match"])
    return {
        "schema_version": "Phase7ExtractionEvaluation.v1",
        "fixture_count": len(results),
        "candidate_exact_match": sum(item["exact_match"] for item in results)
        / len(results),
        "source_link_rate": sum(item["source_linked"] for item in results)
        / len(results),
        "warning_exact_match": sum(item["warning_exact_match"] for item in results)
        / len(results),
        "subgroups": {
            dimension: {
                value: sum(outcomes) / len(outcomes)
                for value, outcomes in values.items()
            }
            for dimension, values in subgroup.items()
        },
        "results": results,
        "limitations": [
            "synthetic OCR-region input only",
            "no handwriting or real camera/OCR measurement",
            "prescription class only",
            "release thresholds pending owner approval",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate_manifest(args.manifest)
    rendered = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
