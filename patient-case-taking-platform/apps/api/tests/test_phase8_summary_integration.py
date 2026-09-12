"""Live PostgreSQL evidence for the tenant-scoped Phase 8 summary workflow."""

import os
from typing import AsyncIterator
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from app.llm.providers import MockClinicalProvider
from app.llm.service import LLMRouter
from app.migrations import apply_migrations
from app.summary_workflow.context import PostgresSummaryContextRepository
from app.summary_workflow.contracts import (
    ConfirmEncounterContextCommand,
    SummarySourceBundle,
    SummaryStatus,
)
from app.summary_workflow.outbox_publisher import PostgresSummaryOutbox
from app.summary_workflow.repository import (
    PostgresSummaryRepository,
    SummaryConflict,
    SummaryNotFound,
)
from app.summary_workflow.service import SummaryTransitionError, SummaryWorkflowService

pytestmark = pytest.mark.skipif(
    os.getenv("PHASE8_INTEGRATION") != "1",
    reason="set PHASE8_INTEGRATION=1 when local PostgreSQL is running",
)

DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://notmid:notmid-local-only@localhost:5432/notmid",
)


@pytest_asyncio.fixture
async def repository() -> AsyncIterator[tuple[PostgresSummaryRepository, asyncpg.Pool, str]]:
    suffix = uuid4().hex
    schema = f"phase8_{suffix}"
    role = f"phase8_role_{suffix}"
    admin = await asyncpg.connect(DATABASE_URL)
    pool = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        await admin.execute(f'SET search_path TO "{schema}"')
        await apply_migrations(admin)
        await admin.execute(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS')
        await admin.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
        await admin.execute(
            f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'
        )

        async def initialize(connection: asyncpg.Connection) -> None:
            await connection.execute(f'SET ROLE "{role}"')
            await connection.execute(f'SET search_path TO "{schema}"')

        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2, setup=initialize)
        assert pool is not None
        yield PostgresSummaryRepository(pool), pool, schema
    finally:
        if pool is not None:
            await pool.close()
        await admin.execute("RESET ROLE")
        await admin.execute("SET search_path TO public")
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.execute(f'DROP ROLE IF EXISTS "{role}"')
        await admin.close()


def _source() -> SummarySourceBundle:
    return SummarySourceBundle(
        tenant_id=uuid4(),
        facility_id=uuid4(),
        patient_id=uuid4(),
        encounter_id=uuid4(),
        chief_complaint="Chest discomfort",
        confirmed_answers={"site": "central", "severity": 7},
        deterministic_red_flags=["RF-RESP-001"],
    )


@pytest.mark.asyncio
async def test_postgres_workflow_is_tenant_scoped_idempotent_and_metadata_only(repository):
    repo, pool, _schema = repository
    service = SummaryWorkflowService(repo, LLMRouter(MockClinicalProvider()))
    source = _source()
    actor = uuid4()
    created = await service.generate(
        source=source, actor_id=actor, actor_role="doctor", idempotency_key="pg-generate"
    )
    replay = await service.generate(
        source=source, actor_id=actor, actor_role="doctor", idempotency_key="pg-generate"
    )
    assert replay.id == created.id
    with pytest.raises(SummaryNotFound):
        await repo.get(tenant_id=uuid4(), summary_id=created.id)
    with pytest.raises(SummaryConflict):
        await service.generate(
            source=source.model_copy(update={"chief_complaint": "Changed"}),
            actor_id=actor,
            actor_role="doctor",
            idempotency_key="pg-generate",
        )

    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('app.tenant_id', $1, true)", str(source.tenant_id)
            )
            outbox = await connection.fetchrow(
                "SELECT payload FROM clinical_summary_outbox WHERE tenant_id = $1",
                source.tenant_id,
            )
    assert outbox is not None
    assert "Chest discomfort" not in str(outbox["payload"])


@pytest.mark.asyncio
async def test_postgres_signing_is_atomic_and_signed_record_is_locked(repository):
    repo, _pool, _schema = repository
    service = SummaryWorkflowService(repo, LLMRouter(MockClinicalProvider()))
    source = _source()
    actor = uuid4()
    draft = await service.generate(
        source=source, actor_id=actor, actor_role="doctor", idempotency_key="pg-sign"
    )
    submitted = await service.submit(
        tenant_id=source.tenant_id,
        summary_id=draft.id,
        actor_id=actor,
        actor_role="doctor",
        expected_version=draft.lock_version,
    )
    signed = await service.sign(
        tenant_id=source.tenant_id,
        summary_id=draft.id,
        actor_id=actor,
        actor_role="doctor",
        expected_version=submitted.lock_version,
    )
    assert signed.status == SummaryStatus.SIGNED
    assert len(await repo.history(tenant_id=source.tenant_id, summary_id=draft.id)) == 3
    with pytest.raises(SummaryTransitionError):
        await service.reject(
            tenant_id=source.tenant_id,
            summary_id=draft.id,
            actor_id=actor,
            actor_role="doctor",
            expected_version=signed.lock_version,
            reason="too late",
        )


@pytest.mark.asyncio
async def test_postgres_context_recomputes_flags_and_rejects_stale_confirmation(repository):
    _repo, pool, _schema = repository
    contexts = PostgresSummaryContextRepository(pool)
    tenant_id, facility_id, patient_id, encounter_id, actor_id = (uuid4() for _ in range(5))
    command = ConfirmEncounterContextCommand(
        facility_id=facility_id,
        patient_id=patient_id,
        encounter_id=encounter_id,
        chief_complaint="difficulty breathing",
        confirmed_answers={"severity": 8},
    )
    confirmed = await contexts.confirm(tenant_id=tenant_id, actor_id=actor_id, command=command)
    assert "RF-RESP-001" in confirmed.deterministic_red_flags
    assembled = await contexts.assemble(
        tenant_id=tenant_id,
        facility_id=facility_id,
        patient_id=patient_id,
        encounter_id=encounter_id,
        language="en",
    )
    assert assembled.chief_complaint == "difficulty breathing"
    with pytest.raises(SummaryConflict):
        await contexts.confirm(
            tenant_id=tenant_id,
            actor_id=actor_id,
            command=command.model_copy(update={"expected_version": 99}),
        )


@pytest.mark.asyncio
async def test_postgres_regeneration_is_atomic_and_idempotent(repository):
    repo, _pool, _schema = repository
    service = SummaryWorkflowService(repo, LLMRouter(MockClinicalProvider()))
    source = _source()
    actor = uuid4()
    draft = await service.generate(
        source=source, actor_id=actor, actor_role="doctor", idempotency_key="pg-old"
    )
    rejected = await service.reject(
        tenant_id=source.tenant_id,
        summary_id=draft.id,
        actor_id=actor,
        actor_role="doctor",
        expected_version=1,
        reason="Clarify evidence",
    )
    replacement = await service.regenerate(
        source=source,
        previous_summary_id=draft.id,
        actor_id=actor,
        actor_role="doctor",
        expected_version=rejected.lock_version,
        idempotency_key="pg-regenerate",
    )
    replay = await service.regenerate(
        source=source,
        previous_summary_id=draft.id,
        actor_id=actor,
        actor_role="doctor",
        expected_version=rejected.lock_version,
        idempotency_key="pg-regenerate",
    )
    previous = await repo.get(tenant_id=source.tenant_id, summary_id=draft.id)
    assert previous.status == SummaryStatus.SUPERSEDED
    assert replacement.id == replay.id
    assert replacement.parent_summary_id == draft.id
    assert [
        item.action for item in await repo.history(tenant_id=source.tenant_id, summary_id=draft.id)
    ] == ["generated", "rejected", "regenerated"]


@pytest.mark.asyncio
async def test_postgres_outbox_publisher_claims_and_marks_summary_event(repository):
    repo, _pool, schema = repository
    service = SummaryWorkflowService(repo, LLMRouter(MockClinicalProvider()))
    source = _source()
    created = await service.generate(
        source=source,
        actor_id=uuid4(),
        actor_role="doctor",
        idempotency_key="pg-publish",
    )

    async def initialize(connection: asyncpg.Connection) -> None:
        await connection.execute(f'SET search_path TO "{schema}"')

    publisher_pool = await asyncpg.create_pool(
        DATABASE_URL, min_size=1, max_size=1, setup=initialize
    )
    try:
        outbox = PostgresSummaryOutbox(publisher_pool, lease_seconds=9)
        events = await outbox.claim(limit=10)
        event = next(item for item in events if item.summary_id == created.id)
        assert event.payload == {
            "status": "draft",
            "summary_id": str(created.id),
            "actor_role": "doctor",
            "lock_version": 1,
        }
        await outbox.mark_published(event.event_id)
        async with publisher_pool.acquire() as connection:
            published_at = await connection.fetchval(
                "SELECT published_at FROM clinical_summary_outbox WHERE event_id = $1",
                event.event_id,
            )
        assert published_at is not None
    finally:
        await publisher_pool.close()
