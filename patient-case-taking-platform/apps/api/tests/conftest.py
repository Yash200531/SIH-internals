import os

# ─── Environment overrides — must happen BEFORE any app import ────────────────
os.environ["ENABLE_DEMO_ROUTES"] = "true"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["ASR_PROVIDER"] = "mock"
os.environ["TTS_PROVIDER"] = "mock"
os.environ["DOCUMENT_WORKFLOW_ENABLED"] = "false"
os.environ["SUMMARY_WORKFLOW_ENABLED"] = "false"
os.environ["READINESS_TIMEOUT_SECONDS"] = "0.05"
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://notmid:notmid-local-only@127.0.0.1:5432/notmid",
)

# ─── Standard imports ─────────────────────────────────────────────────────────
from typing import AsyncIterator
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from app.migrations import apply_migrations

DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://notmid:notmid-local-only@127.0.0.1:5432/notmid",
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_provider_singletons():
    """Reset provider singletons before/after every test."""
    import app.asr.registry as asr_reg
    import app.llm.service as llm_svc
    import app.tts.registry as tts_reg

    tts_reg._provider = None
    llm_svc.reset_llm_router()
    asr_reg._active = None

    yield

    tts_reg._provider = None
    llm_svc.reset_llm_router()
    asr_reg._active = None


@pytest_asyncio.fixture
async def repositories() -> AsyncIterator[tuple[asyncpg.Pool, str]]:
    """Isolated PostgreSQL schema fixture for patient-portal integration tests."""
    suffix = uuid4().hex
    schema = f"patient_portal_{suffix}"
    role = f"patient_portal_role_{suffix}"
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
        yield pool, schema
    finally:
        if pool is not None:
            await pool.close()
        await admin.execute("RESET ROLE")
        await admin.execute("SET search_path TO public")
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.execute(f'DROP ROLE IF EXISTS "{role}"')
        await admin.close()
