"""Opt-in real Kafka-to-Elasticsearch projection check."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.search.contracts import ClinicalSearchQuery, ClinicalSearchRecord, SourceKind
from app.search.elasticsearch_store import ElasticsearchClinicalSearchStore
from app.search.events import ClinicalSearchProjector
from app.search.query import load_synonym_rules
from app.search.worker import process_message

pytestmark = pytest.mark.skipif(
    os.getenv("PHASE9_KAFKA_INTEGRATION") != "1",
    reason="set PHASE9_KAFKA_INTEGRATION=1 with Kafka and Elasticsearch running",
)


class _CanonicalRepository:
    def __init__(self, record: ClinicalSearchRecord) -> None:
        self.record = record

    async def get_signed_summary_record(self, **_kwargs):
        return self.record

    async def list_document_fact_records(self, **_kwargs):
        return []


@pytest.mark.asyncio
async def test_real_kafka_message_projects_once_and_commits_exact_offset() -> None:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    from aiokafka.admin import AIOKafkaAdminClient
    from aiokafka.structs import TopicPartition
    from elasticsearch import AsyncElasticsearch

    token = uuid4().hex
    summary_topic = f"phase9-summary-{token}"
    document_topic = f"phase9-document-{token}"
    alias = f"medikiosk-phase9-kafka-{token}"
    brokers = os.getenv("TEST_KAFKA_BROKERS", "127.0.0.1:9092")
    client = AsyncElasticsearch(
        os.getenv("TEST_ELASTICSEARCH_URL", "http://127.0.0.1:9200"),
        request_timeout=15,
    )
    synonym_path = Path(__file__).resolve().parents[1] / "app/search/medical_synonyms.json"
    store = ElasticsearchClinicalSearchStore(
        client,
        alias=alias,
        synonym_rules=load_synonym_rules(synonym_path),
    )
    source_id = uuid4()
    record = ClinicalSearchRecord(
        record_id=f"summary:{source_id}",
        tenant_id=uuid4(),
        facility_id=uuid4(),
        patient_id=uuid4(),
        encounter_id=uuid4(),
        source_kind=SourceKind.SIGNED_SUMMARY,
        source_id=source_id,
        title="Cardiology discharge summary",
        content="Reviewed myocardial infarction",
        occurred_at=datetime.now(UTC),
        security_labels=["human-reviewed", "clinician-signed"],
    )
    event = json.dumps(
        {
            "event_id": str(uuid4()),
            "tenant_id": str(record.tenant_id),
            "summary_id": str(source_id),
            "event_type": "clinical.summary.signed.v1",
            "event_version": 1,
            "payload": {"summary_id": str(source_id), "status": "signed"},
        }
    ).encode()
    producer = AIOKafkaProducer(bootstrap_servers=brokers, acks="all")
    consumer = AIOKafkaConsumer(
        summary_topic,
        document_topic,
        bootstrap_servers=brokers,
        group_id=f"phase9-test-{token}",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    admin = AIOKafkaAdminClient(bootstrap_servers=brokers)

    try:
        await producer.start()
        await producer.send_and_wait(summary_topic, event, key=str(source_id).encode())
        await consumer.start()
        message = await consumer.getone()
        projector = ClinicalSearchProjector(_CanonicalRepository(record), store)
        assert await process_message(
            consumer=consumer,
            projector=projector,
            message=message,
            summary_topic=summary_topic,
            document_topic=document_topic,
        ) is True
        partition = TopicPartition(message.topic, message.partition)
        assert await consumer.committed(partition) == message.offset + 1

        await producer.send_and_wait(summary_topic, event, key=str(source_id).encode())
        replay = await consumer.getone()
        await process_message(
            consumer=consumer,
            projector=projector,
            message=replay,
            summary_topic=summary_topic,
            document_topic=document_topic,
        )
        result = await store.search(
            ClinicalSearchQuery(
                tenant_id=record.tenant_id,
                patient_id=record.patient_id,
                facility_ids=(record.facility_id,),
                q="heart attack",
            )
        )
        assert result.total == 1
        assert result.hits[0].source_id == source_id
    finally:
        await consumer.stop()
        await producer.stop()
        try:
            owned_indices = await client.indices.get(
                index=f"{alias}-*",
                allow_no_indices=True,
                ignore_unavailable=True,
            )
            for index_name in owned_indices:
                await client.indices.delete(index=index_name)
        finally:
            await store.close()
        await admin.start()
        try:
            await admin.delete_topics([summary_topic, document_topic])
        finally:
            await admin.close()
