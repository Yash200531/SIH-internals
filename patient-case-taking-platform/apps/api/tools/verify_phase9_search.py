"""Run a reproducible, synthetic Phase 9 Elasticsearch verification benchmark."""

import argparse
import asyncio
import json
import math
import platform
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.config import settings
from app.search.contracts import ClinicalSearchQuery, ClinicalSearchRecord, SourceKind
from app.search.elasticsearch_store import ElasticsearchClinicalSearchStore
from app.search.query import load_synonym_rules

TENANT_ID = UUID("90000000-0000-4000-8000-000000000001")
PATIENT_ID = UUID("90000000-0000-4000-8000-000000000002")
FACILITY_ID = UUID("90000000-0000-4000-8000-000000000003")
OTHER_TENANT_ID = UUID("90000000-0000-4000-8000-000000000004")
CORPUS_TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)


def nearest_rank(values: list[float], percentile: int) -> float:
    if not values or not 1 <= percentile <= 100:
        raise ValueError("values and a percentile from 1 to 100 are required")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percentile / 100) - 1)]


def _record(index: int, *, tenant_id: UUID = TENANT_ID) -> ClinicalSearchRecord:
    source_id = uuid5(NAMESPACE_URL, f"medikiosk-phase9-benchmark:{tenant_id}:{index}")
    cases = {
        0: ("Cardiology discharge summary", "Reviewed acute myocardial infarction"),
        1: ("Medication review", "Reviewed metformin 500 mg daily"),
        2: ("Allergy review", "Reviewed penicillin allergy"),
        3: ("मधुमेह अनुवर्ती", "चिकित्सक द्वारा मधुमेह की समीक्षा"),
    }
    title, content = cases.get(
        index,
        (f"Routine review {index:05d}", f"Reviewed routine follow-up code {index:05d}"),
    )
    return ClinicalSearchRecord(
        record_id=f"summary:{source_id}",
        tenant_id=tenant_id,
        facility_id=FACILITY_ID,
        patient_id=PATIENT_ID,
        encounter_id=uuid5(NAMESPACE_URL, f"medikiosk-phase9-encounter:{index}"),
        source_kind=SourceKind.SIGNED_SUMMARY,
        source_id=source_id,
        title=title,
        content=content,
        occurred_at=CORPUS_TIMESTAMP + timedelta(minutes=index),
        security_labels=["human-reviewed", "clinician-signed", "restricted"],
    )


def build_corpus(record_count: int) -> tuple[list[ClinicalSearchRecord], dict[str, str]]:
    if not 10 <= record_count <= 5_000:
        raise ValueError("record_count must be between 10 and 5000")
    visible = [_record(index) for index in range(record_count)]
    hidden = _record(0, tenant_id=OTHER_TENANT_ID)
    expected = {
        "heart attack": visible[0].record_id,
        "metformin": visible[1].record_id,
        "penicillin": visible[2].record_id,
        "मधुमेह": visible[3].record_id,
    }
    return [*visible, hidden], expected


async def run_benchmark(*, record_count: int, iterations: int) -> dict[str, object]:
    if not 1 <= iterations <= 100:
        raise ValueError("iterations must be between 1 and 100")
    from elasticsearch import AsyncElasticsearch

    alias = f"medikiosk-phase9-benchmark-{uuid4().hex}"
    client = AsyncElasticsearch(settings.ELASTICSEARCH_URL, request_timeout=30)
    store = ElasticsearchClinicalSearchStore(
        client,
        alias=alias,
        synonym_rules=load_synonym_rules(
            Path(__file__).resolve().parents[1] / "app/search/medical_synonyms.json"
        ),
    )
    records, expected = build_corpus(record_count)
    query_results: list[dict[str, object]] = []
    started = time.perf_counter()
    try:
        if not await store.ready():
            raise RuntimeError("Elasticsearch is not ready")
        await store.rebuild(records)
        for query_text, expected_id in expected.items():
            observed_ms: list[float] = []
            server_ms: list[int] = []
            for _ in range(iterations):
                query_started = time.perf_counter()
                response = await store.search(
                    ClinicalSearchQuery(
                        tenant_id=TENANT_ID,
                        patient_id=PATIENT_ID,
                        facility_ids=(FACILITY_ID,),
                        q=query_text,
                        page_size=10,
                    )
                )
                observed_ms.append((time.perf_counter() - query_started) * 1000)
                server_ms.append(response.took_ms)
                returned_ids = {hit.record_id for hit in response.hits}
                if response.total != 1 or expected_id not in returned_ids:
                    raise RuntimeError(f"golden query failed: {query_text}")
            query_results.append(
                {
                    "query": query_text,
                    "expected_record_id": expected_id,
                    "iterations": iterations,
                    "observed_latency_ms": {
                        "p50": round(nearest_rank(observed_ms, 50), 3),
                        "p95": round(nearest_rank(observed_ms, 95), 3),
                        "max": round(max(observed_ms), 3),
                    },
                    "elasticsearch_took_ms": {
                        "p50": nearest_rank([float(value) for value in server_ms], 50),
                        "p95": nearest_rank([float(value) for value in server_ms], 95),
                        "max": max(server_ms),
                    },
                    "passed": True,
                }
            )
        reconciliation = await store.reconcile_tenant(
            tenant_id=TENANT_ID,
            canonical_record_ids={
                record.record_id for record in records if record.tenant_id == TENANT_ID
            },
        )
        info_response = await client.info()
        info = info_response.body if hasattr(info_response, "body") else info_response
        return {
            "schema_version": "phase9-search-benchmark-v1",
            "status": "PASS",
            "generated_at": datetime.now(UTC).isoformat(),
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "elasticsearch": info.get("version", {}).get("number", "unknown"),
            },
            "corpus": {
                "generator": "deterministic-uuid5",
                "visible_records": record_count,
                "cross_tenant_control_records": 1,
                "indexed_records": len(records),
            },
            "correctness": {
                "golden_queries": len(expected),
                "golden_queries_passed": len(query_results),
                "tenant_reconciliation_matches": reconciliation.matches,
                "canonical_count": reconciliation.canonical_count,
                "indexed_count": reconciliation.indexed_count,
            },
            "queries": query_results,
            "total_duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    finally:
        try:
            owned = await client.indices.get(
                index=f"{alias}-*",
                allow_no_indices=True,
                ignore_unavailable=True,
            )
            for owned_index in owned:
                await client.indices.delete(index=owned_index)
        finally:
            await store.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify Phase 9 search with a disposable synthetic corpus"
    )
    parser.add_argument("--record-count", type=int, default=250)
    parser.add_argument("--iterations", type=int, default=5)
    return parser


def main() -> None:
    args = _parser().parse_args()
    print(
        json.dumps(
            asyncio.run(
                run_benchmark(
                    record_count=args.record_count,
                    iterations=args.iterations,
                )
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
