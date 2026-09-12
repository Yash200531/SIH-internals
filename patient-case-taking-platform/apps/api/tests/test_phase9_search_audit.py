"""Schema and repository contract checks for Phase 9 retrieval audit."""

from pathlib import Path
from uuid import uuid4

import pytest

from app.search.audit import (
    ClinicalSearchAuditRecord,
    PostgresClinicalSearchAuditRepository,
)

MIGRATIONS = Path(__file__).parents[1] / "migrations"


def _entry() -> ClinicalSearchAuditRecord:
    return ClinicalSearchAuditRecord(
        tenant_id=uuid4(),
        patient_id=uuid4(),
        actor_id=uuid4(),
        actor_role="doctor",
        action="search",
        authorized_facility_ids=(uuid4(),),
        query_sha256="a" * 64,
        filter_metadata={"source_kind": "signed_summary", "cursor_present": False},
        result_count=2,
        latency_ms=7,
        outcome="success",
        correlation_id=uuid4(),
    )


def test_migration_is_tenant_scoped_and_metadata_only() -> None:
    sql = (MIGRATIONS / "0014_clinical_search_audit.up.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE TABLE clinical_search_audit" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "current_setting('app.tenant_id'" in sql
    assert "query_sha256" in sql
    assert "filter_metadata" in sql
    assert "query_text" not in sql
    assert "clinical_content" not in sql


def test_migration_has_a_rollback() -> None:
    sql = (MIGRATIONS / "0014_clinical_search_audit.down.sql").read_text(
        encoding="utf-8"
    )

    assert "DROP TABLE IF EXISTS clinical_search_audit" in sql


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(self, sql: str, *args: object) -> None:
        self.calls.append((sql, args))


class _Acquire:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, *_args):
        return None


class _Pool:
    def __init__(self) -> None:
        self.connection = _Connection()

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


@pytest.mark.asyncio
async def test_repository_sets_tenant_and_persists_no_raw_query() -> None:
    pool = _Pool()
    entry = _entry()

    await PostgresClinicalSearchAuditRepository(pool).record(entry)

    assert pool.connection.calls[0] == (
        "SELECT set_config('app.tenant_id', $1, true)",
        (str(entry.tenant_id),),
    )
    insert_sql, insert_args = pool.connection.calls[1]
    assert "INSERT INTO clinical_search_audit" in insert_sql
    assert insert_args[8] == "a" * 64
    assert "signed_summary" in str(insert_args[9])
    assert "private clinical query" not in str(insert_args)
