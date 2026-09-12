"""Phase 6 contract tests for deterministic triage evaluation."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.audit.emitter import audit_emitter
from app.main import app
from app.rules.triage import NO_CONFIGURED_FLAG, evaluate_text_sources

client = TestClient(app)


@pytest.mark.parametrize("answer", ["Breathing Difficulty", "सांस लेने में तकलीफ"])
def test_confirmed_touch_option_triggers_with_original_source_path(answer):
    evaluation = evaluate_text_sources({"confirmed_answers.cc_main": answer})
    assert [flag.rule_id for flag in evaluation.flags] == ["RF-RESP-001"]
    assert evaluation.flags[0].evidence_paths == ("confirmed_answers.cc_main",)
    assert evaluate_text_sources({"confirmed_answers.cc_main": "no breathing difficulty"}).flags == ()


def test_canonical_ruleset_returns_versioned_owned_flag_with_source_path() -> None:
    evaluation = evaluate_text_sources(
        {"confirmed_answers.associated_symptoms": "I cannot breathe"}
    )

    assert evaluation.outcome == "flags_triggered"
    assert evaluation.ruleset_version == "phase6.prototype.v2"
    assert len(evaluation.flags) == 1

    flag = evaluation.flags[0]
    assert flag.rule_id == "RF-RESP-001"
    assert flag.rule_version == "1.0.1"
    assert flag.ruleset_version == evaluation.ruleset_version
    assert flag.owner_role == "triage_nurse"
    assert flag.requires_acknowledgement is True
    assert flag.evidence_paths == ("confirmed_answers.associated_symptoms",)


def test_hindi_warning_phrase_uses_same_canonical_rule() -> None:
    evaluation = evaluate_text_sources(
        {"last_patient_message": "मुझे सांस लेने में तकलीफ है"}
    )

    assert [flag.rule_id for flag in evaluation.flags] == ["RF-RESP-001"]
    assert evaluation.flags[0].evidence_paths == ("last_patient_message",)


def test_explicit_negation_does_not_trigger_prototype_text_rule() -> None:
    evaluation = evaluate_text_sources(
        {"confirmed_answers.associated_symptoms": "I have no difficulty breathing"}
    )

    assert evaluation.outcome == NO_CONFIGURED_FLAG
    assert evaluation.flags == ()


def test_no_rule_match_is_not_reported_as_routine_or_safe() -> None:
    evaluation = evaluate_text_sources({"chief_complaint": "mild ankle discomfort"})

    assert evaluation.outcome == NO_CONFIGURED_FLAG
    assert "routine" not in evaluation.outcome
    assert "safe" not in evaluation.outcome


def test_phase5_dialogue_uses_the_canonical_phase6_rule_id() -> None:
    response = client.post(
        "/api/v1/clinical-ai/dialogue/next",
        json={
            "tenant_id": str(uuid4()),
            "session_id": str(uuid4()),
            "language": "en",
            "chief_complaint": "breathing concern",
            "last_patient_message": "I cannot breathe",
            "collected_answers": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["safety_flags"] == ["RF-RESP-001"]


def test_demo_triage_endpoint_returns_metadata_without_copying_source_text() -> None:
    audit_emitter._events.clear()
    private_text = "My chest feels heavy"

    response = client.post(
        "/api/v1/triage/evaluate",
        json={
            "tenant_id": str(uuid4()),
            "facility_id": str(uuid4()),
            "encounter_id": str(uuid4()),
            "input_version": 1,
            "idempotency_key": "phase6-contract-1",
            "language": "en",
            "chief_complaint": private_text,
            "confirmed_answers": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "flags_triggered"
    assert body["ruleset_version"] == "phase6.prototype.v2"
    assert body["flags"][0]["rule_id"] == "RF-CARDIAC-001"
    assert body["flags"][0]["evidence_paths"] == ["chief_complaint"]
    assert private_text not in str(body)

    event = audit_emitter._events[-1]
    assert event["metadata"]["rule_ids"] == ["RF-CARDIAC-001"]
    assert private_text not in str(event)


def test_demo_triage_endpoint_rejects_unbounded_answer_collections() -> None:
    response = client.post(
        "/api/v1/triage/evaluate",
        json={
            "tenant_id": str(uuid4()),
            "facility_id": str(uuid4()),
            "encounter_id": str(uuid4()),
            "input_version": 1,
            "idempotency_key": "phase6-contract-2",
            "language": "en",
            "chief_complaint": "headache",
            "confirmed_answers": {f"field_{index}": "value" for index in range(101)},
        },
    )

    assert response.status_code == 422


def test_demo_triage_endpoint_rejects_uncontrolled_evidence_path_keys() -> None:
    response = client.post(
        "/api/v1/triage/evaluate",
        json={
            "tenant_id": str(uuid4()),
            "facility_id": str(uuid4()),
            "encounter_id": str(uuid4()),
            "input_version": 1,
            "idempotency_key": "phase6-contract-3",
            "language": "en",
            "chief_complaint": "headache",
            "confirmed_answers": {"uncontrolled evidence label": "value"},
        },
    )

    assert response.status_code == 422
