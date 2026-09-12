"""Kafka consumer and controlled rebuild entry point for clinical search."""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

from app.config import settings
from app.search.elasticsearch_store import ElasticsearchClinicalSearchStore
from app.search.events import ClinicalSearchProjector, parse_projection_event
from app.search.projection import PostgresClinicalProjectionRepository
from app.search.query import load_synonym_rules

logger = logging.getLogger(__name__)


async def process_message(
    *,
    consumer: Any,
    projector: ClinicalSearchProjector,
    message: Any,
    summary_topic: str,
    document_topic: str,
) -> bool:
    """Project one message and commit only its partition offset after success."""
    from aiokafka.structs import OffsetAndMetadata, TopicPartition

    event = parse_projection_event(
        message.value,
        topic=message.topic,
        summary_topic=summary_topic,
        document_topic=document_topic,
    )
    if event is not None:
        await projector.project(event)
    partition = TopicPartition(message.topic, message.partition)
    await consumer.commit({partition: OffsetAndMetadata(message.offset + 1, "")})
    return event is not None


async def consume_forever(
    *,
    consumer: Any,
    projector: ClinicalSearchProjector,
    summary_topic: str,
    document_topic: str,
    retry_seconds: float = 2.0,
) -> None:
    from aiokafka.structs import TopicPartition

    async for message in consumer:
        try:
            projected = await process_message(
                consumer=consumer,
                projector=projector,
                message=message,
                summary_topic=summary_topic,
                document_topic=document_topic,
            )
            logger.info(
                "Clinical search event handled",
                extra={
                    "topic": message.topic,
                    "partition": message.partition,
                    "offset": message.offset,
                    "projected": projected,
                },
            )
        except Exception:
            logger.exception(
                "Clinical search event projection failed",
                extra={
                    "topic": message.topic,
                    "partition": message.partition,
                    "offset": message.offset,
                },
            )
            consumer.seek(
                TopicPartition(message.topic, message.partition),
                message.offset,
            )
            await asyncio.sleep(retry_seconds)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain the MediKiosk search projection")
    parser.add_argument(
        "command", choices=("forever", "rebuild-tenant", "reconcile-tenant")
    )
    parser.add_argument("--tenant-id", type=UUID)
    return parser


async def _run(command: str, tenant_id: UUID | None) -> None:
    if not settings.CLINICAL_SEARCH_ENABLED:
        raise RuntimeError("CLINICAL_SEARCH_ENABLED must be true")
    if not settings.DATABASE_MAINTENANCE_URL:
        raise RuntimeError("DATABASE_MAINTENANCE_URL is required")

    from elasticsearch import AsyncElasticsearch

    pool = await asyncpg.create_pool(
        settings.DATABASE_MAINTENANCE_URL,
        min_size=1,
        max_size=4,
    )
    client = AsyncElasticsearch(settings.ELASTICSEARCH_URL, request_timeout=15)
    store = ElasticsearchClinicalSearchStore(
        client,
        alias=settings.CLINICAL_SEARCH_INDEX_ALIAS,
        synonym_rules=load_synonym_rules(Path(__file__).with_name("medical_synonyms.json")),
    )
    repository = PostgresClinicalProjectionRepository(pool)
    try:
        if not await store.ready():
            raise RuntimeError("Elasticsearch is not ready")
        if command != "reconcile-tenant":
            await store.ensure_index()
        if command in {"rebuild-tenant", "reconcile-tenant"}:
            if tenant_id is None:
                raise RuntimeError(f"--tenant-id is required for {command}")
            records = await repository.list_tenant_records(tenant_id=tenant_id)
            if command == "rebuild-tenant":
                await store.replace_tenant_records(
                    tenant_id=tenant_id,
                    records=records,
                )
            reconciliation = await store.reconcile_tenant(
                tenant_id=tenant_id,
                canonical_record_ids={record.record_id for record in records},
            )
            print(
                json.dumps(
                    {
                        "command": command,
                        "tenant_id": str(tenant_id),
                        "canonical_count": reconciliation.canonical_count,
                        "indexed_count": reconciliation.indexed_count,
                        "missing_count": len(reconciliation.missing_record_ids),
                        "unexpected_count": len(reconciliation.unexpected_record_ids),
                        "missing_record_ids": list(
                            reconciliation.missing_record_ids[:20]
                        ),
                        "unexpected_record_ids": list(
                            reconciliation.unexpected_record_ids[:20]
                        ),
                        "matches": reconciliation.matches,
                    },
                    sort_keys=True,
                )
            )
            if not reconciliation.matches:
                raise RuntimeError("clinical search reconciliation mismatch")
            return

        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            settings.SUMMARY_EVENT_TOPIC,
            settings.DOCUMENT_EVENT_TOPIC,
            bootstrap_servers=settings.KAFKA_BROKERS,
            group_id=settings.SEARCH_CONSUMER_GROUP,
            client_id="medikiosk-clinical-search",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        try:
            await consume_forever(
                consumer=consumer,
                projector=ClinicalSearchProjector(repository, store),
                summary_topic=settings.SUMMARY_EVENT_TOPIC,
                document_topic=settings.DOCUMENT_EVENT_TOPIC,
            )
        finally:
            await consumer.stop()
    finally:
        await store.close()
        await pool.close()


def main() -> None:
    args = _parser().parse_args()
    asyncio.run(_run(args.command, args.tenant_id))


if __name__ == "__main__":
    main()
