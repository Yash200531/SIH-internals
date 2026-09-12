"""FastAPI dependencies and lifecycle for the Phase 9 search service."""

import asyncio
from pathlib import Path

from fastapi import HTTPException

from app.config import settings
from app.database import get_postgres_pool
from app.search.audit import PostgresClinicalSearchAuditRepository
from app.search.elasticsearch_store import ElasticsearchClinicalSearchStore
from app.search.projection import PostgresClinicalProjectionRepository
from app.search.query import load_synonym_rules
from app.search.service import ClinicalSearchService

_store: ElasticsearchClinicalSearchStore | None = None
_store_lock = asyncio.Lock()


async def get_clinical_search_store() -> ElasticsearchClinicalSearchStore:
    global _store
    if not settings.CLINICAL_SEARCH_ENABLED:
        raise HTTPException(status_code=503, detail="Clinical search is not enabled")
    if _store is None:
        async with _store_lock:
            if _store is None:
                from elasticsearch import AsyncElasticsearch

                client = AsyncElasticsearch(settings.ELASTICSEARCH_URL, request_timeout=15)
                candidate = ElasticsearchClinicalSearchStore(
                    client,
                    alias=settings.CLINICAL_SEARCH_INDEX_ALIAS,
                    synonym_rules=load_synonym_rules(
                        Path(__file__).with_name("medical_synonyms.json")
                    ),
                )
                if not await candidate.ready():
                    await candidate.close()
                    raise HTTPException(
                        status_code=503, detail="Clinical search is temporarily unavailable"
                    )
                _store = candidate
    return _store


async def get_clinical_search_service() -> ClinicalSearchService:
    pool = await get_postgres_pool()
    return ClinicalSearchService(
        await get_clinical_search_store(),
        PostgresClinicalProjectionRepository(pool),
        PostgresClinicalSearchAuditRepository(pool),
    )


async def close_clinical_search_store() -> None:
    global _store
    if _store is not None:
        await _store.close()
        _store = None
