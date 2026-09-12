"""Phase 5 contract tests for the offline mock clinical provider."""

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.audit.emitter import audit_emitter
from app.config import settings
from app.llm.providers import MockClinicalProvider, build_provider
from app.llm.schemas import ClinicalSummaryRequest, DialogueRequest
from app.llm.service import LLMRouter
from app.main import app

client = TestClient(app)


def _dialogue_request(**overrides: Any) -> DialogueRequest:
    values: dict[str, Any] = {
        "tenant_id": uuid4(),
        "session_id": uuid4(),
        "language": "en",
        "chief_complaint": "stomach pain",
        "last_patient_message": "",
        "collected_answers": {},
    }
    values.update(overrides)
    return DialogueRequest(**values)


def test_phase5_defaults_to_offline_mock_provider() -> None:
    assert settings.LLM_PROVIDER == "mock"
    assert isinstance(build_provider(settings.LLM_PROVIDER), MockClinicalProvider)


@pytest.mark.asyncio
async def test_dialogue_uses_socrates_order() -> None:
    response = await LLMRouter(MockClinicalProvider()).next_question(_dialogue_request())
    assert response.provider == "mock"
    assert response.next_domain == "site"
    assert response.escalation_required is False
    assert response.confidence.not_clinical_probability is True
    assert response.evidence[0].source_path == "ontology.socrates.site"


@pytest.mark.asyncio
async def test_red_flag_bypasses_normal_dialogue() -> None:
    response = await LLMRouter(MockClinicalProvider()).next_question(
        _dialogue_request(last_patient_message="My chest feels heavy and I cannot breathe")
    )
    assert response.answer_type == "urgent_action"
    assert response.escalation_required is True
    assert "RF-RESP-001" in response.safety_flags
    assert any(item.source_path == "last_patient_message" for item in response.evidence)


@pytest.mark.asyncio
async def test_summary_contains_confirmed_facts_and_requires_review() -> None:
    request = ClinicalSummaryRequest(
        tenant_id=uuid4(),
        encounter_id=uuid4(),
        chief_complaint="Headache",
        confirmed_answers={"site": "forehead", "severity": 6},
        document_facts=["Paracetamol listed in uploaded prescription"],
    )
    response = await LLMRouter(MockClinicalProvider()).generate_summary(request)
    assert response.provider == "mock"
    assert response.clinician_review_required is True
    assert any("Site: forehead" in fact for fact in response.history_of_present_illness)
    assert response.document_facts == ["Paracetamol listed in uploaded prescription"]
    assert response.confidence.basis == "structured_completeness"
    assert any(item.source_path == "confirmed_answers.site" for item in response.evidence)


class InvalidProvider:
    name = "invalid-test-provider"
    external_network_used = False

    def __init__(self) -> None:
        self.calls = 0

    async def health(self) -> bool:
        return False

    async def generate(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return {"not": "the required schema"}


@pytest.mark.asyncio
async def test_invalid_output_retries_then_uses_safe_template() -> None:
    provider = InvalidProvider()
    response = await LLMRouter(provider, max_attempts=3).next_question(_dialogue_request())
    assert provider.calls == 3
    assert response.provider == "template-fallback"
    assert response.degraded is True


@pytest.mark.asyncio
async def test_fallback_does_not_drop_deterministic_red_flags() -> None:
    request = ClinicalSummaryRequest(
        tenant_id=uuid4(),
        encounter_id=uuid4(),
        chief_complaint="Fever",
        confirmed_answers={"associated_symptoms": "difficulty breathing"},
    )
    response = await LLMRouter(InvalidProvider(), max_attempts=1).generate_summary(request)
    assert "RF-RESP-001" in response.red_flags


def test_health_endpoint_confirms_no_external_network() -> None:
    response = client.get("/api/v1/clinical-ai/health")
    assert response.status_code == 200
    assert response.json() == {
        "provider": "mock",
        "ready": True,
        "external_network_used": False,
    }


def test_dialogue_endpoint_emits_metadata_only_audit_event() -> None:
    audit_emitter._events.clear()
    payload = _dialogue_request(last_patient_message="private patient statement").model_dump(
        mode="json"
    )
    response = client.post("/api/v1/clinical-ai/dialogue/next", json=payload)
    assert response.status_code == 200
    event = audit_emitter._events[-1]
    assert event["metadata"]["provider"] == "mock"
    assert "private patient statement" not in str(event)


def test_assisted_dialogue_endpoint_reaches_editable_summary_contract() -> None:
    tenant_id = str(uuid4())
    session_id = str(uuid4())
    encounter_id = str(uuid4())
    answers: dict[str, str] = {}
    expected_domains = (
        "site",
        "onset",
        "character",
        "radiation",
        "associated_symptoms",
        "timing",
        "exacerbating_relieving_factors",
        "severity",
    )

    for domain in expected_domains:
        response = client.post(
            "/api/v1/clinical-ai/dialogue/next",
            json={
                "tenant_id": tenant_id,
                "session_id": session_id,
                "language": "en",
                "chief_complaint": "stomach pain",
                "last_patient_message": answers.get(domain, ""),
                "collected_answers": answers,
            },
        )
        assert response.status_code == 200
        assert response.json()["next_domain"] == domain
        answers[domain] = "6" if domain == "severity" else f"confirmed {domain} answer"

    review = client.post(
        "/api/v1/clinical-ai/dialogue/next",
        json={
            "tenant_id": tenant_id,
            "session_id": session_id,
            "language": "en",
            "chief_complaint": "stomach pain",
            "last_patient_message": answers["severity"],
            "collected_answers": answers,
        },
    )
    assert review.status_code == 200
    assert review.json()["answer_type"] == "review"

    summary = client.post(
        "/api/v1/clinical-ai/summaries/generate",
        json={
            "tenant_id": tenant_id,
            "encounter_id": encounter_id,
            "language": "en",
            "chief_complaint": "stomach pain",
            "confirmed_answers": answers,
            "transcript": "",
            "document_facts": [],
        },
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["provider"] == "mock"
    assert body["clinician_review_required"] is True
    assert body["uncertainties"] == []
    assert len(body["history_of_present_illness"]) == len(expected_domains)


def test_assisted_dialogue_endpoint_interrupts_for_emergency_message() -> None:
    payload = _dialogue_request(
        language="hi",
        last_patient_message="मुझे सांस लेने में तकलीफ है",
    ).model_dump(mode="json")
    response = client.post("/api/v1/clinical-ai/dialogue/next", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["escalation_required"] is True
    assert body["answer_type"] == "urgent_action"
    assert "RF-RESP-001" in body["safety_flags"]
