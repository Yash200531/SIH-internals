"""Transactional and privacy tests for document review persistence."""

import json
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from uuid import uuid4

import pytest

from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.review import (
    CandidateDecision,
    ManualCandidate,
    ReviewAction,
    ReviewConflict,
    ReviewIncomplete,
)
from app.documents.review_repository import PostgresDocumentReviewRepository


class _Context(AbstractAsyncContextManager):
    def __init__(self, value: Any) -> None:
        self.value = value

    async def __aenter__(self) -> Any:
        return self.value

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class _Connection:
    def __init__(
        self,
        *,
        fetchrows: list[dict[str, Any] | None],
        fetches: list[list[dict[str, Any]]] | None = None,
    ) -> None:
        self.fetchrows = fetchrows
        self.fetches = fetches or []
        self.executions: list[tuple[str, tuple[Any, ...]]] = []

    def transaction(self) -> _Context:
        return _Context(self)

    async def execute(self, query: str, *args: Any) -> str:
        self.executions.append((query, args))
        return "INSERT 0 1"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.executions.append((query, args))
        return self.fetchrows.pop(0)

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.executions.append((query, args))
        return self.fetches.pop(0)


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Context:
        return _Context(self.connection)


def _document(version: int = 12) -> DocumentRegistryEntry:
    return DocumentRegistryEntry(
        tenant_id=uuid4(),
        facility_id=uuid4(),
        patient_id=uuid4(),
        encounter_id=uuid4(),
        uploader_actor_id=uuid4(),
        purpose="treatment",
        consent_reference="consent/synthetic-v1",
        original_filename="synthetic-prescription.png",
        declared_document_class="prescription",
        declared_mime="image/png",
        declared_size_bytes=24,
        idempotency_key="review-repository-test",
        state=DocumentState.REVIEW_REQUIRED,
        version=version,
    )


def _candidate(*, version: int = 1, state: str = "unreviewed") -> dict[str, Any]:
    return {
        "candidate_id": uuid4(),
        "entity_type": "strength",
        "normalized_value": "500",
        "unit": "mg",
        "source_page_artifact_id": uuid4(),
        "source_ocr_artifact_id": uuid4(),
        "source_region_id": uuid4(),
        "source_page_number": 1,
        "parser_signal": "prescription.strength.v1",
        "negated": False,
        "temporality": "document_unspecified",
        "subject": "patient",
        "uncertainty": None,
        "document_statement": True,
        "clinician_confirmed_current": False,
        "review_state": state,
        "version": version,
    }


@pytest.mark.asyncio
async def test_accept_is_candidate_versioned_append_only_and_phi_minimized() -> None:
    document = _document()
    before = _candidate()
    after = {**before, "review_state": "accepted", "version": 2}
    connection = _Connection(
        fetchrows=[document.model_dump(), None, before, after]
    )
    repository = PostgresDocumentReviewRepository(_Pool(connection))

    reviewed = await repository.decide(
        tenant_id=document.tenant_id,
        document_id=document.id,
        facility_ids={document.facility_id},
        actor_id=uuid4(),
        actor_role="nurse",
        idempotency_key="decision-1",
        candidate_id=before["candidate_id"],
        decision=CandidateDecision(
            action=ReviewAction.ACCEPT,
            expected_candidate_version=1,
            source_verified=True,
        ),
    )

    assert reviewed.review_state.value == "accepted"
    assert reviewed.version == 2
    serialized = str(connection.executions)
    assert "INSERT INTO document_review_decision" in serialized
    event_args = next(
        args for query, args in connection.executions if "INSERT INTO document_outbox" in query
    )
    assert "DocumentReviewDecisionRecorded.v1" in event_args
    event_payload = json.loads(event_args[-1])
    assert set(event_payload) == {
        "decision_id",
        "candidate_id",
        "action",
        "candidate_version",
    }
    assert document.original_filename not in str(event_args)
    assert str(document.patient_id) not in str(event_args)


@pytest.mark.asyncio
async def test_stale_candidate_decision_is_rejected_without_writes() -> None:
    document = _document()
    current = _candidate(version=2)
    connection = _Connection(fetchrows=[document.model_dump(), None, current])
    repository = PostgresDocumentReviewRepository(_Pool(connection))

    with pytest.raises(ReviewConflict, match="version is stale"):
        await repository.decide(
            tenant_id=document.tenant_id,
            document_id=document.id,
            facility_ids={document.facility_id},
            actor_id=uuid4(),
            actor_role="doctor",
            idempotency_key="stale-decision",
            candidate_id=current["candidate_id"],
            decision=CandidateDecision(
                action=ReviewAction.ACCEPT,
                expected_candidate_version=1,
                source_verified=True,
            ),
        )

    assert not any("UPDATE document_extraction_candidate" in q for q, _ in connection.executions)
    assert not any("INSERT INTO document_review_decision" in q for q, _ in connection.executions)


@pytest.mark.asyncio
async def test_finalize_refuses_partial_review() -> None:
    document = _document()
    connection = _Connection(
        fetchrows=[document.model_dump(), {"total": 2, "unresolved": 1}]
    )
    repository = PostgresDocumentReviewRepository(_Pool(connection))

    with pytest.raises(ReviewIncomplete, match="Every candidate"):
        await repository.finalize(
            tenant_id=document.tenant_id,
            document_id=document.id,
            facility_ids={document.facility_id},
            actor_id=uuid4(),
            actor_role="doctor",
            expected_document_version=document.version,
            idempotency_key="finalize-partial",
        )

    assert not any("UPDATE document_registry" in q for q, _ in connection.executions)


@pytest.mark.asyncio
async def test_manual_entry_is_source_linked_append_only_and_not_in_event_payload() -> None:
    document = _document()
    page_id = uuid4()
    manual_row = {
        **_candidate(version=2, state="corrected"),
        "candidate_id": uuid4(),
        "entity_type": "instructions",
        "normalized_value": "after food",
        "unit": None,
        "source_page_artifact_id": page_id,
        "source_ocr_artifact_id": None,
        "source_region_id": None,
    }
    connection = _Connection(
        fetchrows=[
            document.model_dump(),
            None,
            {"id": page_id, "page_number": 1, "width": 800, "height": 1200},
            manual_row,
        ]
    )
    repository = PostgresDocumentReviewRepository(_Pool(connection))

    result = await repository.add_manual_candidate(
        tenant_id=document.tenant_id,
        document_id=document.id,
        facility_ids={document.facility_id},
        actor_id=uuid4(),
        actor_role="doctor",
        idempotency_key="manual-1",
        candidate=ManualCandidate(
            entity_type="instructions",
            normalized_value="after food",
            unit=None,
            source_page_artifact_id=page_id,
            source_page_number=1,
            source_verified=True,
        ),
    )

    assert result.review_state.value == "corrected"
    assert result.source_ocr_artifact_id is None
    assert "INSERT INTO document_review_decision" in str(connection.executions)
    event_args = next(
        args for query, args in connection.executions if "INSERT INTO document_outbox" in query
    )
    assert "after food" not in str(event_args)


@pytest.mark.asyncio
async def test_failed_automation_can_open_manual_review_when_pages_exist() -> None:
    document = _document().model_copy(
        update={"state": DocumentState.PROCESSING_FAILED}
    )
    page = {
        "id": uuid4(),
        "page_number": 1,
        "width": 900,
        "height": 1200,
        "preprocessing_version": "normalize.v1",
    }
    updated = document.model_copy(
        update={
            "state": DocumentState.REVIEW_REQUIRED,
            "version": document.version + 1,
            "updated_at": datetime.now(UTC),
        }
    )
    connection = _Connection(
        fetchrows=[document.model_dump(), updated.model_dump()],
        fetches=[[page]],
    )
    repository = PostgresDocumentReviewRepository(_Pool(connection))

    review = await repository.open_manual_review(
        tenant_id=document.tenant_id,
        document_id=document.id,
        facility_ids={document.facility_id},
        actor_id=uuid4(),
        actor_role="nurse",
        expected_document_version=document.version,
        idempotency_key="manual-fallback-1",
    )

    assert review.state == "review_required"
    assert review.candidates == ()
    assert review.pages[0].id == page["id"]
    assert "DocumentManualReviewRequested.v1" in str(connection.executions)


@pytest.mark.asyncio
async def test_manual_review_requires_a_normalized_source_page() -> None:
    document = _document().model_copy(
        update={"state": DocumentState.PROCESSING_FAILED}
    )
    connection = _Connection(fetchrows=[document.model_dump()], fetches=[[]])
    repository = PostgresDocumentReviewRepository(_Pool(connection))

    with pytest.raises(ReviewIncomplete, match="normalization"):
        await repository.open_manual_review(
            tenant_id=document.tenant_id,
            document_id=document.id,
            facility_ids={document.facility_id},
            actor_id=uuid4(),
            actor_role="doctor",
            expected_document_version=document.version,
            idempotency_key="manual-fallback-no-page",
        )


@pytest.mark.asyncio
async def test_finalize_moves_only_fully_decided_document_to_reviewed() -> None:
    document = _document()
    accepted = _candidate(version=2, state="accepted")
    rejected = _candidate(version=2, state="rejected")
    updated = document.model_copy(
        update={
            "state": DocumentState.REVIEWED,
            "version": document.version + 1,
            "reviewed_document_class": "prescription",
            "updated_at": datetime.now(UTC),
        }
    )
    connection = _Connection(
        fetchrows=[
            document.model_dump(),
            {"total": 2, "unresolved": 0},
            updated.model_dump(),
        ],
        fetches=[[accepted, rejected]],
    )
    repository = PostgresDocumentReviewRepository(_Pool(connection))

    result = await repository.finalize(
        tenant_id=document.tenant_id,
        document_id=document.id,
        facility_ids={document.facility_id},
        actor_id=uuid4(),
        actor_role="doctor",
        expected_document_version=document.version,
        idempotency_key="finalize-complete",
    )

    assert result.state == "reviewed"
    assert result.document_class == "prescription"
    assert {candidate.review_state.value for candidate in result.candidates} == {
        "accepted",
        "rejected",
    }
    assert "DocumentReviewCompleted.v1" in str(connection.executions)


@pytest.mark.asyncio
async def test_finalize_retry_replays_only_the_matching_completion() -> None:
    document = _document().model_copy(update={"state": DocumentState.REVIEWED})
    accepted = _candidate(version=2, state="accepted")
    connection = _Connection(
        fetchrows=[document.model_dump(), {"event_id": uuid4()}],
        fetches=[[accepted]],
    )
    repository = PostgresDocumentReviewRepository(_Pool(connection))

    replay = await repository.finalize(
        tenant_id=document.tenant_id,
        document_id=document.id,
        facility_ids={document.facility_id},
        actor_id=uuid4(),
        actor_role="doctor",
        expected_document_version=document.version - 1,
        idempotency_key="same-finalization",
    )

    assert replay.state == "reviewed"
    assert not any("UPDATE document_registry" in q for q, _ in connection.executions)
