"""Real Elasticsearch evidence for the Phase 9 derived search boundary."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.search.contracts import ClinicalSearchQuery, ClinicalSearchRecord, SourceKind
from app.search.elasticsearch_store import ElasticsearchClinicalSearchStore
from app.search.query import load_synonym_rules

pytestmark = pytest.mark.skipif(
    os.getenv("PHASE9_INTEGRATION") != "1",
    reason="set PHASE9_INTEGRATION=1 when local Elasticsearch is running",
)


def _record(
    *,
    tenant_id,
    patient_id,
    facility_id,
    title: str,
    content: str,
    occurred_at: datetime,
    source_kind: SourceKind = SourceKind.SIGNED_SUMMARY,
    document_id=None,
    entity_type=None,
) -> ClinicalSearchRecord:
    source_id = uuid4()
    return ClinicalSearchRecord(
        record_id=f"{source_kind.value}:{source_id}",
        tenant_id=tenant_id,
        facility_id=facility_id,
        patient_id=patient_id,
        encounter_id=uuid4(),
        document_id=document_id,
        source_kind=source_kind,
        source_id=source_id,
        title=title,
        content=content,
        entity_type=entity_type,
        statement_status="document_stated"
        if source_kind is SourceKind.REVIEWED_FACT
        else None,
        occurred_at=occurred_at,
        security_labels=["human-reviewed", "restricted"],
    )


@pytest.mark.asyncio
async def test_real_elasticsearch_search_filters_synonyms_replacement_and_rebuild() -> None:
    from elasticsearch import AsyncElasticsearch

    alias = f"medikiosk-phase9-test-{uuid4().hex}"
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
    tenant_id, patient_id, facility_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    visible = _record(
        tenant_id=tenant_id,
        patient_id=patient_id,
        facility_id=facility_id,
        title="Cardiology discharge summary",
        content="Acute myocardial infarction reviewed and signed",
        occurred_at=now,
    )
    wrong_patient = _record(
        tenant_id=tenant_id,
        patient_id=uuid4(),
        facility_id=facility_id,
        title="Other patient summary",
        content="Acute myocardial infarction",
        occurred_at=now,
    )
    wrong_tenant = _record(
        tenant_id=uuid4(),
        patient_id=patient_id,
        facility_id=facility_id,
        title="Other tenant summary",
        content="Acute myocardial infarction",
        occurred_at=now,
    )
    wrong_facility = _record(
        tenant_id=tenant_id,
        patient_id=patient_id,
        facility_id=uuid4(),
        title="Other facility summary",
        content="Acute myocardial infarction",
        occurred_at=now,
    )

    try:
        assert await store.ready() is True
        await store.bulk_upsert([visible, wrong_patient, wrong_tenant, wrong_facility])
        result = await store.search(
            ClinicalSearchQuery(
                tenant_id=tenant_id,
                patient_id=patient_id,
                facility_ids=(facility_id,),
                q="heart attack",
            )
        )
        assert result.total == 1
        assert [hit.source_id for hit in result.hits] == [visible.source_id]
        assert result.facets.source_kinds == {"signed_summary": 1}
        assert result.hits[0].highlights

        document_id = uuid4()
        old_fact = _record(
            tenant_id=tenant_id,
            patient_id=patient_id,
            facility_id=facility_id,
            title="Medication statement",
            content="Metformin 500 mg",
            occurred_at=now - timedelta(days=1),
            source_kind=SourceKind.REVIEWED_FACT,
            document_id=document_id,
            entity_type="medication_statement",
        )
        await store.replace_document_records(
            tenant_id=tenant_id,
            document_id=document_id,
            records=[old_fact],
        )
        assert (
            await store.search(
                ClinicalSearchQuery(
                    tenant_id=tenant_id,
                    patient_id=patient_id,
                    facility_ids=(facility_id,),
                    q="Metformin",
                    source_kind=SourceKind.REVIEWED_FACT,
                )
            )
        ).total == 1

        await store.replace_document_records(
            tenant_id=tenant_id,
            document_id=document_id,
            records=[],
        )
        assert (
            await store.search(
                ClinicalSearchQuery(
                    tenant_id=tenant_id,
                    patient_id=patient_id,
                    facility_ids=(facility_id,),
                    q="Metformin",
                )
            )
        ).total == 0

        rebuilt = await store.rebuild([visible])
        assert rebuilt.indexed_count == 1
        assert rebuilt.previous_indexes
        assert (
            await store.search(
                ClinicalSearchQuery(
                    tenant_id=tenant_id,
                    patient_id=patient_id,
                    facility_ids=(facility_id,),
                    q="heart attack",
                )
            )
        ).total == 1
    finally:
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
