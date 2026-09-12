"""Opt-in real PostgreSQL evidence for the Phase 9 audit boundary."""

import json
import os
from typing import AsyncIterator
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from app.migrations import apply_migrations
from app.search.audit import (
    ClinicalSearchAuditRecord,
    PostgresClinicalSearchAuditRepository,
)

pytestmark = pytest.mark.skipif(
    os.getenv("PHASE9_POSTGRES_INTEGRATION") != "1",
    reason="set PHASE9_POSTGRES_INTEGRATION=1 with local PostgreSQL running",
)

DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://notmid:notmid-local-only@localhost:5432/notmid",
)


@pytest_asyncio.fixture
async def audit_database() -> AsyncIterator[tuple[asyncpg.Pool, str]]:
    suffix = uuid4().hex
    schema = f"phase9_audit_{suffix}"
    role = f"phase9_audit_role_{suffix}"
    admin = await asyncpg.connect(DATABASE_URL)
    pool: asyncpg.Pool | None = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        await admin.execute(f'SET search_path TO "{schema}"')
        assert await apply_migrations(admin) == 19
        await admin.execute(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS')
        await admin.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
        await admin.execute(
            f'GRANT SELECT, INSERT ON "{schema}".clinical_search_audit TO "{role}"'
        )

        async def initialize(connection: asyncpg.Connection) -> None:
            await connection.execute(f'SET ROLE "{role}"')
            await connection.execute(f'SET search_path TO "{schema}"')

        pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=2,
            setup=initialize,
        )
        assert pool is not None
        yield pool, schema
    finally:
        if pool is not None:
            await pool.close()
        await admin.execute("RESET ROLE")
        await admin.execute("SET search_path TO public")
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.execute(f'DROP ROLE IF EXISTS "{role}"')
        await admin.close()


@pytest.mark.asyncio
async def test_real_audit_insert_is_durable_metadata_only_and_rls_isolated(
    audit_database: tuple[asyncpg.Pool, str],
) -> None:
    pool, _schema = audit_database
    tenant_id, other_tenant_id = uuid4(), uuid4()
    entry = ClinicalSearchAuditRecord(
        tenant_id=tenant_id,
        patient_id=uuid4(),
        actor_id=uuid4(),
        actor_role="doctor",
        action="search",
        authorized_facility_ids=(uuid4(),),
        query_sha256="b" * 64,
        filter_metadata={"source_kind": "signed_summary", "cursor_present": False},
        result_count=1,
        latency_ms=11,
        outcome="success",
        correlation_id=uuid4(),
    )

    await PostgresClinicalSearchAuditRepository(pool).record(entry)

    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
            )
            visible = await connection.fetchrow(
                "SELECT * FROM clinical_search_audit WHERE id = $1", entry.id
            )
        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('app.tenant_id', $1, true)", str(other_tenant_id)
            )
            hidden = await connection.fetchrow(
                "SELECT * FROM clinical_search_audit WHERE id = $1", entry.id
            )
        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('app.tenant_id', $1, true)", str(other_tenant_id)
            )
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    """
                    INSERT INTO clinical_search_audit (
                        id, tenant_id, patient_id, actor_id, actor_role, action,
                        purpose, authorized_facility_ids, query_sha256,
                        filter_metadata, result_count, latency_ms, outcome,
                        correlation_id
                    ) VALUES (
                        $1, $2, $3, $4, 'doctor', 'search', 'treatment',
                        $5::UUID[], $6, '{}'::JSONB, 0, 1, 'success', $7
                    )
                    """,
                    uuid4(),
                    tenant_id,
                    uuid4(),
                    uuid4(),
                    [uuid4()],
                    "c" * 64,
                    uuid4(),
                )

    assert visible is not None
    assert visible["query_sha256"] == "b" * 64
    assert json.loads(visible["filter_metadata"]) == {
        "source_kind": "signed_summary",
        "cursor_present": False,
    }
    assert "private clinical query" not in str(dict(visible))
    assert hidden is None
