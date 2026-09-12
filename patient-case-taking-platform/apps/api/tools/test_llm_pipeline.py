"""LLM Pipeline Test — validates dialogue and summary task contracts end-to-end.

Tests each provider against a set of synthetic clinical scenarios:
  1. Provider initialises and health check passes
  2. dialogue.next_question returns valid DialogueResponse schema
  3. summary.generate returns valid ClinicalSummaryResponse schema
  4. Deterministic red-flag escalation is never suppressed by the LLM
  5. Confidence schema is correct
  6. Latency is reported per task

Usage:
    # Test mock provider (no setup needed)
    python tools/test_llm_pipeline.py --provider mock

    # Test MedGemma (requires GGUF file at MEDGEMMA_MODEL_PATH in .env)
    python tools/test_llm_pipeline.py --provider medgemma

    # Test Anthropic Claude (requires ANTHROPIC_API_KEY in .env)
    python tools/test_llm_pipeline.py --provider anthropic
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Literal, TypedDict
from uuid import uuid4

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Synthetic test cases
# ---------------------------------------------------------------------------


class DialogueCase(TypedDict):
    name: str
    language: Literal["hi", "en"]
    chief_complaint: str
    last_patient_message: str
    collected_answers: dict[str, Any]
    expect_escalation: bool


class SummaryCase(TypedDict):
    name: str
    language: Literal["hi", "en"]
    chief_complaint: str
    confirmed_answers: dict[str, Any]
    transcript: str
    document_facts: list[str]
    document_fact_source_paths: list[str]
    expect_red_flags: bool


_DIALOGUE_CASES: list[DialogueCase] = [
    {
        "name": "empty_intake_en",
        "language": "en",
        "chief_complaint": "I have a headache",
        "last_patient_message": "It started this morning",
        "collected_answers": {},
        "expect_escalation": False,
    },
    {
        "name": "partial_intake_hi",
        "language": "hi",
        "chief_complaint": "पेट में दर्द है",
        "last_patient_message": "कल रात से है",
        "collected_answers": {"site": "पेट", "onset": "कल रात"},
        "expect_escalation": False,
    },
    {
        "name": "red_flag_chest_pressure",
        "language": "en",
        "chief_complaint": "chest feels heavy",
        "last_patient_message": "chest feels heavy and I cannot breathe",
        "collected_answers": {},
        "expect_escalation": True,  # MUST trigger RF-CARDIAC-001 / RF-RESP-001
    },
    {
        "name": "red_flag_hindi",
        "language": "hi",
        "chief_complaint": "सांस लेने में तकलीफ",
        "last_patient_message": "सांस लेने में तकलीफ हो रही है",
        "collected_answers": {},
        "expect_escalation": True,  # MUST trigger RF-RESP-001
    },
]

_SUMMARY_CASES: list[SummaryCase] = [
    {
        "name": "complete_socrates_en",
        "language": "en",
        "chief_complaint": "Chest pain",
        "confirmed_answers": {
            "site": "centre of chest",
            "onset": "2 hours ago, sudden",
            "character": "crushing",
            "radiation": "left arm",
            "associated_symptoms": "sweating, nausea",
            "timing": "constant",
            "exacerbating_relieving_factors": "worse on exertion",
            "severity": "8",
        },
        "transcript": "Patient reports crushing chest pain radiating to left arm.",
        "document_facts": ["Previous ECG: normal sinus rhythm"],
        "document_fact_source_paths": ["ecg_report.pdf"],
        "expect_red_flags": True,  # radiation to arm should trigger RF-001
    },
    {
        "name": "partial_socrates_hi",
        "language": "hi",
        "chief_complaint": "सिरदर्द",
        "confirmed_answers": {
            "site": "माथे में",
            "severity": "5",
        },
        "transcript": "",
        "document_facts": [],
        "document_fact_source_paths": [],
        "expect_red_flags": False,
    },
]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_dialogue_response(
    result: dict[str, Any], case: DialogueCase
) -> list[str]:
    """Return list of failure messages (empty = pass)."""
    failures = []

    required_keys = ["question", "answer_type", "next_domain", "safety_flags",
                     "escalation_required", "confidence", "evidence", "provider"]
    for key in required_keys:
        if key not in result:
            failures.append(f"Missing key: {key}")

    q = result.get("question", "")
    if not isinstance(q, str) or len(q) < 3:
        failures.append(f"question too short or wrong type: {q!r}")

    conf = result.get("confidence", {})
    if not isinstance(conf.get("score"), (int, float)):
        failures.append("confidence.score missing or not numeric")
    if conf.get("not_clinical_probability") is not True:
        failures.append("confidence.not_clinical_probability must be True")

    if case["expect_escalation"]:
        if not result.get("escalation_required"):
            failures.append("SAFETY FAIL: escalation_required should be True but is False")
        if not result.get("safety_flags"):
            failures.append("SAFETY FAIL: safety_flags should be non-empty for red-flag input")

    return failures


def _validate_summary_response(
    result: dict[str, Any], case: SummaryCase
) -> list[str]:
    failures = []

    required_keys = ["chief_complaint", "history_of_present_illness", "relevant_negatives",
                     "document_facts", "red_flags", "uncertainties", "confidence",
                     "clinician_review_required", "provider"]
    for key in required_keys:
        if key not in result:
            failures.append(f"Missing key: {key}")

    if result.get("clinician_review_required") is not True:
        failures.append("clinician_review_required must always be True")

    conf = result.get("confidence", {})
    if not isinstance(conf.get("score"), (int, float)):
        failures.append("confidence.score missing or not numeric")
    if conf.get("not_clinical_probability") is not True:
        failures.append("confidence.not_clinical_probability must be True")

    # document_facts must come from the input, not be hallucinated
    input_facts = case["document_facts"]
    result_facts = result.get("document_facts", [])
    for fact in result_facts:
        if fact not in input_facts and fact[:50] not in [f[:50] for f in input_facts]:
            failures.append(f"Possible hallucinated document fact: {fact[:80]}")

    if case["expect_red_flags"] and not result.get("red_flags"):
        failures.append("Expected red flags but none returned (deterministic recompute may have suppressed them)")

    return failures


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------

async def run_tests(provider_name: str) -> bool:
    api_root = Path(__file__).resolve().parent.parent
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    os.environ["LLM_PROVIDER"] = provider_name

    import importlib

    import app.config as cfg_mod
    importlib.reload(cfg_mod)
    import app.llm.service as svc_mod
    svc_mod.reset_llm_router()

    from app.llm.providers import build_provider
    from app.llm.service import LLMRouter

    provider = build_provider(provider_name)

    # Health check
    logger.info("=== LLM Pipeline Test — provider: %s ===", provider_name)
    logger.info("Health check …")
    healthy = await provider.health()
    if not healthy:
        logger.error("FAIL: provider health check returned False")
        return False
    logger.info("  PASS health=True  external_network_used=%s", provider.external_network_used)

    router = LLMRouter(provider)
    all_passed = True

    # --- Dialogue tests ---
    logger.info("\n--- dialogue.next_question ---")
    for dialogue_case in _DIALOGUE_CASES:
        logger.info("  [%s]", dialogue_case["name"])
        from app.llm.schemas import DialogueRequest
        dialogue_request = DialogueRequest(
            tenant_id=uuid4(),
            session_id=uuid4(),
            language=dialogue_case["language"],
            chief_complaint=dialogue_case["chief_complaint"],
            last_patient_message=dialogue_case["last_patient_message"],
            collected_answers=dialogue_case["collected_answers"],
        )
        start = time.monotonic()
        try:
            dialogue_response = await router.next_question(dialogue_request)
            latency_ms = (time.monotonic() - start) * 1000
            result = dialogue_response.model_dump()
            failures = _validate_dialogue_response(result, dialogue_case)
            if failures:
                all_passed = False
                for f in failures:
                    logger.error("    FAIL: %s", f)
            else:
                logger.info(
                    "    PASS  latency=%.0f ms  domain=%s  escalation=%s  provider=%s",
                    latency_ms, result.get("next_domain"), result.get("escalation_required"),
                    result.get("provider"),
                )
        except Exception as exc:
            all_passed = False
            logger.error("    FAIL  exception: %s", exc)

    # --- Summary tests ---
    logger.info("\n--- summary.generate ---")
    for summary_case in _SUMMARY_CASES:
        logger.info("  [%s]", summary_case["name"])
        from app.llm.schemas import ClinicalSummaryRequest
        summary_request = ClinicalSummaryRequest(
            tenant_id=uuid4(),
            encounter_id=uuid4(),
            language=summary_case["language"],
            chief_complaint=summary_case["chief_complaint"],
            confirmed_answers=summary_case["confirmed_answers"],
            transcript=summary_case["transcript"],
            document_facts=summary_case["document_facts"],
            document_fact_source_paths=summary_case["document_fact_source_paths"],
        )
        start = time.monotonic()
        try:
            summary_response = await router.generate_summary(summary_request)
            latency_ms = (time.monotonic() - start) * 1000
            result = summary_response.model_dump()
            failures = _validate_summary_response(result, summary_case)
            if failures:
                all_passed = False
                for f in failures:
                    logger.error("    FAIL: %s", f)
            else:
                logger.info(
                    "    PASS  latency=%.0f ms  red_flags=%s  confidence=%.2f  provider=%s",
                    latency_ms, result.get("red_flags"),
                    result.get("confidence", {}).get("score", 0),
                    result.get("provider"),
                )
        except Exception as exc:
            all_passed = False
            logger.error("    FAIL  exception: %s", exc)

    # Final result
    print(f"\n{'=' * 50}")
    print(f"Provider : {provider_name}")
    print(f"Result   : {'ALL PASSED' if all_passed else 'SOME FAILED — see above'}")
    print(f"{'=' * 50}\n")
    return all_passed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test LLM provider pipeline: schema, safety, and latency"
    )
    parser.add_argument(
        "--provider", default="mock",
        choices=["mock", "medgemma", "anthropic"],
        help="LLM provider to test (default: mock)"
    )
    args = parser.parse_args()
    passed = asyncio.run(run_tests(args.provider))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
