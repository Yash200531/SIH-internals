"""Real database lifecycle, retry and patient/login isolation checks."""

import os
from uuid import uuid4

import asyncpg
import pytest

from app.patient_portal.service import PatientIdentity
from app.patient_portal.sessions import IntakeSessionRepository, IntakeSessionUnavailable

pytestmark = pytest.mark.skipif(os.getenv("PATIENT_SESSION_INTEGRATION") != "1", reason="Requires local PostgreSQL")


async def test_durable_session_ownership_expiry_and_history(repositories):
    pool, _ = repositories
    repo = IntakeSessionRepository(pool)
    facility = uuid4()
    patient = PatientIdentity(uuid4(), uuid4(), {facility})
    owner, other_owner = "a" * 64, "b" * 64
    key = uuid4()
    created = await repo.create(patient, owner, facility, "hi", key)
    assert created["encounter_id"] != created["id"]
    assert (created["hard_expires_at"] - created["expires_at"]).total_seconds() == 1500
    assert await IntakeSessionRepository(pool).create(patient, owner, facility, "hi", key) == created
    with pytest.raises(IntakeSessionUnavailable):
        await repo.create(patient, owner, facility, "en", key)
    for forbidden, login in [
        (patient, other_owner),
        (PatientIdentity(patient.tenant_id, uuid4(), {facility}), owner),
        (PatientIdentity(uuid4(), patient.patient_id, {facility}), owner),
        (PatientIdentity(patient.tenant_id, patient.patient_id, {uuid4()}), owner),
    ]:
        with pytest.raises(IntakeSessionUnavailable):
            await repo.access(forbidden, login, created["id"], touch=True)
    touched = await repo.access(patient, owner, created["id"], touch=True)
    assert touched["expires_at"] >= created["expires_at"]
    assert touched["hard_expires_at"] == created["hard_expires_at"]
    await repo.access(patient, owner, created["id"], end=True)
    with pytest.raises(IntakeSessionUnavailable):
        await repo.access(patient, owner, created["id"], touch=True)
    with pytest.raises(IntakeSessionUnavailable):
        await repo.create(patient, owner, facility, "hi", key)
    async with pool.acquire() as connection:
        async with connection.transaction():
            await repo.scope(connection, patient)
            assert await connection.fetchval("SELECT count(*) FROM patient_intake_session_history") == 2
            await repo.scope(connection, PatientIdentity(patient.tenant_id, uuid4(), {facility}))
            assert await connection.fetchval("SELECT count(*) FROM patient_intake_session") == 0
            assert await connection.fetchval("SELECT count(*) FROM patient_intake_session_history") == 0
        with pytest.raises(asyncpg.RaiseError, match="append-only"):
            async with connection.transaction():
                await repo.scope(connection, patient)
                await connection.execute("UPDATE patient_intake_session_history SET action='ended'")
    expired = await repo.create(patient, owner, facility, "en", uuid4())
    async with pool.acquire() as connection:
        async with connection.transaction():
            await repo.scope(connection, patient)
            await connection.execute("UPDATE patient_intake_session SET expires_at=CURRENT_TIMESTAMP-INTERVAL '1 second' WHERE id=$1", expired["id"])
    with pytest.raises(IntakeSessionUnavailable):
        await repo.access(patient, owner, expired["id"], touch=True)
