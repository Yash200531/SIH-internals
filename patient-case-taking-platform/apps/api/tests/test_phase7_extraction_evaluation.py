"""Frozen-set evaluation harness tests."""

from pathlib import Path

from tools.evaluate_phase7_extraction import evaluate_manifest

MANIFEST = (
    Path(__file__).parents[3]
    / "tests"
    / "model-evaluations"
    / "phase7"
    / "manifest.jsonl"
)


def test_frozen_synthetic_set_has_full_extraction_and_source_link_matches() -> None:
    report = evaluate_manifest(MANIFEST)

    assert report["fixture_count"] == 7
    assert report["candidate_exact_match"] == 1.0
    assert report["source_link_rate"] == 1.0
    assert report["warning_exact_match"] == 1.0
    assert report["limitations"]


def test_evaluation_reports_required_safety_strata() -> None:
    report = evaluate_manifest(MANIFEST)

    assert set(report["subgroups"]) == {
        "document_class",
        "language",
        "script",
        "capture_source",
        "quality",
        "page_type",
    }
    assert set(report["subgroups"]["script"]) == {"Latin", "Devanagari"}
