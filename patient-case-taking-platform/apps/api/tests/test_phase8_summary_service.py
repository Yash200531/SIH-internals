"""Phase 8 domain tests: mock-only generation and clinician-controlled lifecycle."""

from uuid import uuid4

import pytest

from app.llm.providers import MockClinicalProvider
from app.llm.service import LLMRouter
from app.summary_workflow.contracts import SummarySourceBundle, SummaryStatus
from app.summary_workflow.repository import InMemorySummaryRepository, SummaryConflict
from app.summary_workflow.service import (
    SummaryPermissionError,
    SummaryTransitionError,
    SummaryWorkflowService,
)


def _source(**overrides: object) -> SummarySourceBundle:
    values = {
        "tenant_id": uuid4(),
        "facility_id": uuid4(),
        "patient_id": uuid4(),
        "encounter_id": uuid4(),
        "chief_complaint": "Chest discomfort",
        "confirmed_answers": {"site": "centre of chest", "severity": 7},
        "reviewed_document_facts": ["Reviewed medication statement"],
        "deterministic_red_flags": ["RF-RESP-001"],
    }
    values.update(overrides)
    return SummarySourceBundle(**values)


@pytest.fixture
def workflow() -> tuple[SummaryWorkflowService, InMemorySummaryRepository]:
    repository = InMemorySummaryRepository()
    return SummaryWorkflowService(repository, LLMRouter(MockClinicalProvider())), repository


@pytest.mark.asyncio
async def test_generate_is_mock_only_idempotent_and_preserves_required_red_flags(workflow):
    service, repository = workflow
    source = _source()
    actor = uuid4()
    first = await service.generate(
        source=source, actor_id=actor, actor_role="nurse", idempotency_key="generate-1"
    )
    replay = await service.generate(
        source=source, actor_id=actor, actor_role="nurse", idempotency_key="generate-1"
    )
    assert replay.id == first.id
    assert first.provider == "mock"
    assert first.status == SummaryStatus.DRAFT
    assert "RF-RESP-001" in first.content.red_flags
    assert any(item.source_path == "triage.flags.RF-RESP-001" for item in first.evidence)
    assert len(await repository.history(tenant_id=source.tenant_id, summary_id=first.id)) == 1
    with pytest.raises(SummaryConflict, match="another request"):
        await service.generate(
            source=source.model_copy(update={"chief_complaint": "Different complaint"}),
            actor_id=actor,
            actor_role="nurse",
            idempotency_key="generate-1",
        )


@pytest.mark.asyncio
async def test_doctor_can_edit_submit_and_sign_immutable_hash(workflow):
    service, repository = workflow
    source = _source()
    actor = uuid4()
    draft = await service.generate(
        source=source, actor_id=actor, actor_role="doctor", idempotency_key="g-2"
    )
    content = draft.content.model_copy(
        update={"history_of_present_illness": ["Clinician corrected history"]}
    )
    edited = await service.edit(
        tenant_id=source.tenant_id,
        summary_id=draft.id,
        actor_id=actor,
        actor_role="doctor",
        expected_version=1,
        content=content,
    )
    assert any(item.source_type == "clinician_edit" for item in edited.evidence)
    assert not any(
        item.output_path.startswith("history_of_present_illness[")
        for item in edited.evidence
    )
    submitted = await service.submit(
        tenant_id=source.tenant_id,
        summary_id=draft.id,
        actor_id=actor,
        actor_role="doctor",
        expected_version=edited.lock_version,
    )
    signed = await service.sign(
        tenant_id=source.tenant_id,
        summary_id=draft.id,
        actor_id=actor,
        actor_role="doctor",
        expected_version=submitted.lock_version,
    )
    assert signed.status == SummaryStatus.SIGNED
    assert signed.signature_sha256 and len(signed.signature_sha256) == 64
    assert [
        item.action
        for item in await repository.history(tenant_id=source.tenant_id, summary_id=draft.id)
    ] == ["generated", "edited", "submitted", "signed"]
    with pytest.raises(SummaryTransitionError):
        await service.edit(
            tenant_id=source.tenant_id,
            summary_id=draft.id,
            actor_id=actor,
            actor_role="doctor",
            expected_version=signed.lock_version,
            content=content,
        )


@pytest.mark.asyncio
async def test_nurse_cannot_edit_reject_or_sign(workflow):
    service, _ = workflow
    source = _source()
    actor = uuid4()
    draft = await service.generate(
        source=source, actor_id=actor, actor_role="nurse", idempotency_key="g-3"
    )
    with pytest.raises(SummaryPermissionError):
        await service.edit(
            tenant_id=source.tenant_id,
            summary_id=draft.id,
            actor_id=actor,
            actor_role="nurse",
            expected_version=1,
            content=draft.content,
        )


@pytest.mark.asyncio
async def test_edit_cannot_remove_deterministic_red_flag(workflow):
    service, _ = workflow
    source = _source()
    actor = uuid4()
    draft = await service.generate(
        source=source, actor_id=actor, actor_role="doctor", idempotency_key="g-4"
    )
    unsafe = draft.content.model_copy(update={"red_flags": []})
    with pytest.raises(SummaryTransitionError, match="cannot be removed"):
        await service.edit(
            tenant_id=source.tenant_id,
            summary_id=draft.id,
            actor_id=actor,
            actor_role="doctor",
            expected_version=1,
            content=unsafe,
        )


@pytest.mark.asyncio
async def test_stale_version_conflicts_and_cross_tenant_read_is_not_found(workflow):
    service, repository = workflow
    source = _source()
    actor = uuid4()
    draft = await service.generate(
        source=source, actor_id=actor, actor_role="doctor", idempotency_key="g-5"
    )
    with pytest.raises(SummaryConflict):
        await service.submit(
            tenant_id=source.tenant_id,
            summary_id=draft.id,
            actor_id=actor,
            actor_role="doctor",
            expected_version=99,
        )
    with pytest.raises(Exception, match="Summary not found"):
        await repository.get(tenant_id=uuid4(), summary_id=draft.id)


@pytest.mark.asyncio
async def test_rejected_draft_regenerates_as_new_version_and_preserves_history(workflow):
    service, repository = workflow
    source = _source()
    actor = uuid4()
    draft = await service.generate(
        source=source, actor_id=actor, actor_role="doctor", idempotency_key="g-6"
    )
    rejected = await service.reject(
        tenant_id=source.tenant_id,
        summary_id=draft.id,
        actor_id=actor,
        actor_role="doctor",
        expected_version=1,
        reason="Evidence needs clarification",
    )
    replacement = await service.regenerate(
        source=source,
        previous_summary_id=draft.id,
        actor_id=actor,
        actor_role="doctor",
        expected_version=rejected.lock_version,
        idempotency_key="regen-1",
    )
    previous = await repository.get(tenant_id=source.tenant_id, summary_id=draft.id)
    assert previous.status == SummaryStatus.SUPERSEDED
    assert replacement.parent_summary_id == draft.id
    assert replacement.lineage_id == draft.lineage_id
    assert replacement.generation == 2
    replay = await service.regenerate(
        source=source,
        previous_summary_id=draft.id,
        actor_id=actor,
        actor_role="doctor",
        expected_version=rejected.lock_version,
        idempotency_key="regen-1",
    )
    assert replay.id == replacement.id


@pytest.mark.asyncio
async def test_regeneration_cannot_change_patient_or_encounter(workflow):
    service, _repository = workflow
    source = _source()
    actor = uuid4()
    draft = await service.generate(
        source=source, actor_id=actor, actor_role="doctor", idempotency_key="g-7"
    )
    with pytest.raises(SummaryTransitionError, match="must match"):
        await service.regenerate(
            source=source.model_copy(update={"patient_id": uuid4()}),
            previous_summary_id=draft.id,
            actor_id=actor,
            actor_role="doctor",
            expected_version=draft.lock_version,
            idempotency_key="regen-cross-patient",
        )
