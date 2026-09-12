"""Reviewed-fact promotion, replay and projection safety tests."""

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from uuid import uuid4

import pytest

from app.documents.promotion import PostgresReviewedFactRepository
from app.documents.registry import DocumentRegistryEntry, DocumentState


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
        fetches: list[list[dict[str, Any]]],
    ) -> None:
        self.fetchrows = fetchrows
        self.fetches = fetches
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


def _document() -> DocumentRegistryEntry:
    return DocumentRegistryEntry(
        tenant_id=uuid4(),
        facility_id=uuid4(),
        patient_id=uuid4(),
        encounter_id=uuid4(),
        uploader_actor_id=uuid4(),
        purpose="treatment",
        consent_reference="consent/synthetic-v1",
        original_filename="synthetic.png",
        declared_document_class="prescription",
        reviewed_document_class="prescription",
        declared_mime="image/png",
        declared_size_bytes=20,
        idempotency_key="promotion-test",
        state=DocumentState.REVIEWED,
        version=14,
    )


def _candidate(document: DocumentRegistryEntry) -> dict[str, Any]:
    return {
        "candidate_id": uuid4(),
        "candidate_version": 2,
        "review_decision_id": uuid4(),
        "entity_type": "medication_statement",
        "normalized_value": "Metformin",
        "unit": None,
        "source_page_artifact_id": uuid4(),
        "source_ocr_artifact_id": uuid4(),
        "source_region_id": uuid4(),
        "source_page_number": 1,
        "document_statement": True,
        "clinician_confirmed_current": False,
        "patient_id": document.patient_id,
        "encounter_id": document.encounter_id,
        "document_id": document.id,
        "promoted_at": datetime.now(UTC),
    }


@pytest.mark.asyncio
async def test_promote_creates_authoritative_fact_and_rebuildable_projections() -> None:
    document = _document()
    candidate = _candidate(document)
    fact_id = uuid4()
    fact = {**candidate, "id": fact_id}
    connection = _Connection(
        fetchrows=[document.model_dump(), None, {"id": fact_id}],
        fetches=[[candidate], [fact]],
    )
    repository = PostgresReviewedFactRepository(_Pool(connection))

    result = await repository.promote(
        tenant_id=document.tenant_id,
        document_id=document.id,
        source_event_id=uuid4(),
        actor_id=uuid4(),
        actor_role="doctor",
    )

    assert result.promoted_fact_count == 1
    assert result.replayed is False
    serialized = str(connection.executions)
    assert "review_state IN ('accepted', 'corrected')" in serialized
    assert "INSERT INTO reviewed_document_fact" in serialized
    assert "INSERT INTO clinical_timeline_projection" in serialized
    assert "INSERT INTO document_fhir_projection" in serialized
    assert "INSERT INTO document_search_projection" in serialized
    event_args = next(
        args for query, args in connection.executions if "INSERT INTO document_outbox" in query
    )
    assert "ReviewedDocumentFactsPromoted.v1" in event_args
    assert "Metformin" not in str(event_args)
    assert str(document.patient_id) not in str(event_args)


@pytest.mark.asyncio
async def test_promotion_receipt_makes_event_replay_a_no_op() -> None:
    document = _document()
    source_event_id = uuid4()
    connection = _Connection(
        fetchrows=[document.model_dump(), {"promoted_fact_count": 3}],
        fetches=[],
    )
    repository = PostgresReviewedFactRepository(_Pool(connection))

    result = await repository.promote(
        tenant_id=document.tenant_id,
        document_id=document.id,
        source_event_id=source_event_id,
        actor_id=uuid4(),
        actor_role="nurse",
    )

    assert result.promoted_fact_count == 3
    assert result.replayed is True
    assert not any("INSERT INTO reviewed_document_fact" in q for q, _ in connection.executions)


@pytest.mark.asyncio
async def test_rebuild_uses_only_active_authoritative_facts() -> None:
    document = _document()
    fact = {**_candidate(document), "id": uuid4()}
    connection = _Connection(
        fetchrows=[document.model_dump()],
        fetches=[[fact]],
    )
    repository = PostgresReviewedFactRepository(_Pool(connection))

    count = await repository.rebuild_projections(
        tenant_id=document.tenant_id,
        document_id=document.id,
    )

    assert count == 1
    queries = [query for query, _ in connection.executions]
    assert any("WHERE tenant_id = $1 AND document_id = $2 AND active" in q for q in queries)
    assert sum("DELETE FROM" in q for q in queries) == 3


@pytest.mark.asyncio
async def test_withdrawal_preserves_facts_and_history_but_removes_projections() -> None:
    document = _document()
    fact_id = uuid4()
    connection = _Connection(
        fetchrows=[document.model_dump()],
        fetches=[[{"id": fact_id}], []],
    )
    repository = PostgresReviewedFactRepository(_Pool(connection))

    count = await repository.withdraw(
        tenant_id=document.tenant_id,
        document_id=document.id,
        actor_id=uuid4(),
        actor_role="doctor",
        reason_code="entered_in_error",
        facility_ids={document.facility_id},
    )

    assert count == 1
    serialized = str(connection.executions)
    assert "SET active = FALSE" in serialized
    assert "INSERT INTO document_fact_status_history" in serialized
    assert "DELETE FROM clinical_timeline_projection" in serialized
    assert "DELETE FROM reviewed_document_fact" not in serialized


@pytest.mark.asyncio
async def test_only_doctor_can_withdraw_reviewed_facts() -> None:
    document = _document()
    repository = PostgresReviewedFactRepository(
        _Pool(_Connection(fetchrows=[], fetches=[]))
    )

    with pytest.raises(PermissionError, match="Doctor"):
        await repository.withdraw(
            tenant_id=document.tenant_id,
            document_id=document.id,
            actor_id=uuid4(),
            actor_role="nurse",
            reason_code="entered_in_error",
            facility_ids={document.facility_id},
        )
