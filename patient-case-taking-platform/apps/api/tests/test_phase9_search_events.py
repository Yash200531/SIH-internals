import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.search.contracts import ClinicalSearchRecord, SourceKind
from app.search.events import (
    ClinicalSearchProjector,
    InvalidSearchProjectionEvent,
    SearchProjectionEventType,
    parse_projection_event,
)
from app.search.worker import consume_forever, process_message

SUMMARY_TOPIC = "clinical.summaries.v1"
DOCUMENT_TOPIC = "clinical.documents.v1"


def _encoded_event(event_type: str, **updates) -> bytes:
    aggregate_id = uuid4()
    values = {
        "event_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "summary_id": str(aggregate_id),
        "aggregate_id": str(aggregate_id),
        "event_type": event_type,
        "event_version": 1,
        "payload": {},
    }
    values.update(updates)
    return json.dumps(values).encode()


def _record(**updates) -> ClinicalSearchRecord:
    source_id = uuid4()
    values = {
        "record_id": f"summary:{source_id}",
        "tenant_id": uuid4(),
        "facility_id": uuid4(),
        "patient_id": uuid4(),
        "encounter_id": uuid4(),
        "source_kind": SourceKind.SIGNED_SUMMARY,
        "source_id": source_id,
        "title": "Signed summary",
        "content": "Clinician-reviewed content",
        "occurred_at": datetime.now(UTC),
        "security_labels": ["human-reviewed", "clinician-signed"],
    }
    values.update(updates)
    return ClinicalSearchRecord(**values)


def _parse(value: bytes, topic: str):
    return parse_projection_event(
        value,
        topic=topic,
        summary_topic=SUMMARY_TOPIC,
        document_topic=DOCUMENT_TOPIC,
    )


def test_parser_accepts_only_projection_relevant_event_types() -> None:
    signed = _parse(
        _encoded_event(SearchProjectionEventType.SUMMARY_SIGNED),
        SUMMARY_TOPIC,
    )
    promoted = _parse(
        _encoded_event(SearchProjectionEventType.DOCUMENT_FACTS_PROMOTED),
        DOCUMENT_TOPIC,
    )

    assert signed is not None
    assert signed.event_type is SearchProjectionEventType.SUMMARY_SIGNED
    assert promoted is not None
    assert promoted.event_type is SearchProjectionEventType.DOCUMENT_FACTS_PROMOTED
    assert _parse(_encoded_event("clinical.summary.edited.v1"), SUMMARY_TOPIC) is None
    assert _parse(_encoded_event("DocumentReviewCompleted.v1"), DOCUMENT_TOPIC) is None


@pytest.mark.parametrize(
    "value,topic,match",
    [
        (b"not-json", SUMMARY_TOPIC, "UTF-8 JSON"),
        (
            _encoded_event(SearchProjectionEventType.SUMMARY_SIGNED, event_version=2),
            SUMMARY_TOPIC,
            "event_version",
        ),
        (
            _encoded_event(SearchProjectionEventType.SUMMARY_SIGNED, tenant_id="wrong"),
            SUMMARY_TOPIC,
            "tenant_id",
        ),
        (
            _encoded_event(SearchProjectionEventType.SUMMARY_SIGNED),
            "unexpected",
            "unexpected topic",
        ),
    ],
)
def test_parser_rejects_malformed_relevant_events(
    value: bytes, topic: str, match: str
) -> None:
    with pytest.raises(InvalidSearchProjectionEvent, match=match):
        _parse(value, topic)


class _Repository:
    def __init__(self, record: ClinicalSearchRecord | None = None) -> None:
        self.record = record
        self.document_records: list[ClinicalSearchRecord] = []
        self.summary_calls = []
        self.document_calls = []

    async def get_signed_summary_record(self, **kwargs):
        self.summary_calls.append(kwargs)
        return self.record

    async def list_document_fact_records(self, **kwargs):
        self.document_calls.append(kwargs)
        return self.document_records


class _Store:
    def __init__(self) -> None:
        self.upserts = []
        self.deletes = []
        self.replacements = []
        self.fail = False
        self.failures_remaining = 0

    async def upsert(self, record):
        if self.fail or self.failures_remaining:
            self.failures_remaining = max(0, self.failures_remaining - 1)
            raise RuntimeError("index unavailable")
        self.upserts.append(record)

    async def delete_record(self, record_id):
        self.deletes.append(record_id)

    async def replace_document_records(self, **kwargs):
        self.replacements.append(kwargs)
        return len(kwargs["records"])


@pytest.mark.asyncio
async def test_projector_rereads_canonical_summary_and_removes_missing_record() -> None:
    record = _record()
    repository, store = _Repository(record), _Store()
    projector = ClinicalSearchProjector(repository, store)
    value = _encoded_event(
        SearchProjectionEventType.SUMMARY_SIGNED,
        tenant_id=str(record.tenant_id),
        summary_id=str(record.source_id),
    )
    event = _parse(value, SUMMARY_TOPIC)
    assert event is not None

    assert await projector.project(event) == 1
    assert store.upserts == [record]

    repository.record = None
    assert await projector.project(event) == 0
    assert store.deletes == [f"summary:{record.source_id}"]


@pytest.mark.asyncio
async def test_document_events_replace_only_canonical_active_facts() -> None:
    repository, store = _Repository(), _Store()
    fact = _record(
        source_kind=SourceKind.REVIEWED_FACT,
        document_id=uuid4(),
        entity_type="medication_statement",
        statement_status="document_stated",
    )
    repository.document_records = [fact]
    value = _encoded_event(
        SearchProjectionEventType.DOCUMENT_FACTS_WITHDRAWN,
        tenant_id=str(fact.tenant_id),
        aggregate_id=str(fact.document_id),
    )
    event = _parse(value, DOCUMENT_TOPIC)
    assert event is not None

    assert await ClinicalSearchProjector(repository, store).project(event) == 1
    assert store.replacements[0] == {
        "tenant_id": fact.tenant_id,
        "document_id": fact.document_id,
        "records": [fact],
    }


class _Consumer:
    def __init__(self) -> None:
        self.commits = []

    async def commit(self, offsets):
        self.commits.append(offsets)


class _RetryConsumer(_Consumer):
    def __init__(self, messages) -> None:
        super().__init__()
        self.messages = messages
        self.seeks = []

    def __aiter__(self):
        async def messages():
            for message in self.messages:
                yield message

        return messages()

    def seek(self, partition, offset):
        self.seeks.append((partition, offset))


@pytest.mark.asyncio
async def test_message_offset_commits_only_after_successful_projection() -> None:
    record = _record()
    repository, store = _Repository(record), _Store()
    consumer = _Consumer()
    message = SimpleNamespace(
        value=_encoded_event(
            SearchProjectionEventType.SUMMARY_SIGNED,
            tenant_id=str(record.tenant_id),
            summary_id=str(record.source_id),
        ),
        topic=SUMMARY_TOPIC,
        partition=3,
        offset=41,
    )
    projector = ClinicalSearchProjector(repository, store)

    assert await process_message(
        consumer=consumer,
        projector=projector,
        message=message,
        summary_topic=SUMMARY_TOPIC,
        document_topic=DOCUMENT_TOPIC,
    ) is True
    committed = next(iter(consumer.commits[0].values()))
    assert committed.offset == 42

    store.fail = True
    with pytest.raises(RuntimeError, match="index unavailable"):
        await process_message(
            consumer=consumer,
            projector=projector,
            message=message,
            summary_topic=SUMMARY_TOPIC,
            document_topic=DOCUMENT_TOPIC,
        )
    assert len(consumer.commits) == 1


@pytest.mark.asyncio
async def test_consumer_rewinds_failed_offset_then_retries_successfully(monkeypatch) -> None:
    record = _record()
    repository, store = _Repository(record), _Store()
    store.failures_remaining = 1
    message = SimpleNamespace(
        value=_encoded_event(
            SearchProjectionEventType.SUMMARY_SIGNED,
            tenant_id=str(record.tenant_id),
            summary_id=str(record.source_id),
        ),
        topic=SUMMARY_TOPIC,
        partition=2,
        offset=7,
    )
    consumer = _RetryConsumer([message, message])

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr("app.search.worker.asyncio.sleep", no_wait)
    await consume_forever(
        consumer=consumer,
        projector=ClinicalSearchProjector(repository, store),
        summary_topic=SUMMARY_TOPIC,
        document_topic=DOCUMENT_TOPIC,
        retry_seconds=0,
    )

    assert len(consumer.seeks) == 1
    assert consumer.seeks[0][0].topic == SUMMARY_TOPIC
    assert consumer.seeks[0][0].partition == 2
    assert consumer.seeks[0][1] == 7
    assert len(consumer.commits) == 1
    assert store.upserts == [record]
