"""Live PostgreSQL alert transactions, concurrency, RLS and history immutability."""

import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest

from app.rules.alert_lifecycle import AlertActor, AlertCommand, AlertConflict
from app.rules.alert_repository import AlertEvidence, AlertNotFound, PostgresAlertRepository
from app.rules.triage import evaluate_text_sources

pytestmark = pytest.mark.skipif(
    os.getenv("TRIAGE_INTEGRATION") != "1", reason="Set TRIAGE_INTEGRATION=1 with local PostgreSQL"
)


DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://notmid:notmid-local-only@localhost:5432/notmid",
)




async def test_alert_transaction_replay_concurrency_and_scope(repositories):
    pool, _ = repositories
    tenant, facility, encounter = uuid4(), uuid4(), uuid4()
    actor = AlertActor(actor_id=uuid4(), tenant_id=tenant, facility_ids={facility}, role="doctor")
    rule = evaluate_text_sources({"confirmed_answers.breathing": "cannot breathe"}).flags[0]
    repo = PostgresAlertRepository(pool)
    args = dict(
        actor=actor,
        facility_id=facility,
        encounter_id=encounter,
        evidence=AlertEvidence(input_version=1, fingerprint="a" * 64),
        rule=rule,
    )
    first, replay = await asyncio.gather(repo.raise_flag(**args), repo.raise_flag(**args))
    assert first.id == replay.id
    assert len(await repo.list_flags(actor)) == 1
    command = AlertCommand(action="acknowledge", expected_version=1)
    requests = dict(flag_id=first.id, actor=actor, command=command)
    results = await asyncio.gather(
        repo.command(**requests, idempotency_key="ack-1"),
        repo.command(**requests, idempotency_key="ack-2"),
        return_exceptions=True,
    )
    assert sum(isinstance(item, AlertConflict) for item in results) == 1
    successful_key = "ack-1" if not isinstance(results[0], Exception) else "ack-2"
    repeated = await repo.command(**requests, idempotency_key=successful_key)
    assert repeated.version == 2
    with pytest.raises(AlertConflict):
        await repo.command(
            **{**requests, "command": command.model_copy(update={"expected_version": 2})},
            idempotency_key=successful_key,
        )
    for denied in (
        actor.model_copy(update={"tenant_id": uuid4()}),
        actor.model_copy(update={"facility_ids": frozenset({uuid4()})}),
    ):
        assert await repo.list_flags(denied) == []
        with pytest.raises(AlertNotFound):
            await repo.command(
                flag_id=first.id, actor=denied, command=command, idempotency_key="denied"
            )
    async with pool.acquire() as connection:
        async with connection.transaction():
            await repo._tenant(connection, tenant)
            assert await connection.fetchval("SELECT count(*) FROM triage_flag_history") == 2
            assert await connection.fetchval("SELECT count(*) FROM triage_outbox") == 2
            payloads = await connection.fetch("SELECT payload FROM triage_outbox")
            assert "cannot breathe" not in str(payloads)
            assert "rationale" not in str(payloads)
        async with connection.transaction():
            await repo._tenant(connection, uuid4())
            assert await connection.fetchval("SELECT count(*) FROM triage_flag") == 0
            assert await connection.fetchval("SELECT count(*) FROM triage_flag_history") == 0
        with pytest.raises(asyncpg.RaiseError, match="append-only"):
            async with connection.transaction():
                await repo._tenant(connection, tenant)
                await connection.execute("UPDATE triage_flag_history SET action='tampered'")


async def test_failed_outbox_write_rolls_back_flag_history_and_version(repositories, monkeypatch):
    pool, _ = repositories
    tenant, facility = uuid4(), uuid4()
    actor = AlertActor(actor_id=uuid4(), tenant_id=tenant, facility_ids={facility}, role="doctor")
    repo = PostgresAlertRepository(pool)
    rule = evaluate_text_sources({"confirmed_answers.breathing": "cannot breathe"}).flags[0]
    flag = await repo.raise_flag(
        actor=actor,
        facility_id=facility,
        encounter_id=uuid4(),
        evidence=AlertEvidence(input_version=1, fingerprint="b" * 64),
        rule=rule,
    )
    original = repo._record

    async def fail_after_writes(*args):
        await original(*args)
        raise RuntimeError("simulated transaction failure")

    monkeypatch.setattr(repo, "_record", fail_after_writes)
    with pytest.raises(RuntimeError):
        await repo.command(
            flag_id=flag.id,
            actor=actor,
            command=AlertCommand(action="acknowledge", expected_version=1),
            idempotency_key="retry",
        )
    assert (await repo.list_flags(actor))[0]["lifecycle"]["version"] == 1
    async with pool.acquire() as connection:
        async with connection.transaction():
            await repo._tenant(connection, tenant)
            assert await connection.fetchval("SELECT count(*) FROM triage_flag_history") == 1
            assert await connection.fetchval("SELECT count(*) FROM triage_outbox") == 1


async def test_live_alert_api_from_confirmed_intake_through_resolution(repositories, monkeypatch):
    import httpx
    from fastapi import FastAPI

    from app.auth.token import create_dev_token
    from app.patient_portal.consent_repository import PostgresPatientConsentRepository
    from app.patient_portal.contracts import PatientConsentCreate, PatientIntakeSubmissionCreate
    from app.patient_portal.intake_repository import PostgresPatientIntakeRepository
    from app.patient_portal.service import PatientIdentity
    from app.patient_portal.worklist import PostgresIntakeWorklist
    from app.routers import alerts
    from app.summary_workflow.contracts import SummaryContent

    pool, _ = repositories
    tenant, patient, facility, encounter, doctor = (uuid4() for _ in range(5))
    identity = PatientIdentity(tenant_id=tenant, patient_id=patient, facility_ids={facility})
    consent = await PostgresPatientConsentRepository(pool).create(
        identity, PatientConsentCreate(encounter_id=encounter)
    )
    intake = await PostgresPatientIntakeRepository(pool).create(
        identity,
        PatientIntakeSubmissionCreate(
            facility_id=facility,
            encounter_id=encounter,
            session_id=uuid4(),
            consent_id=consent.id,
            language="en",
            chief_complaint="cannot breathe",
            confirmed_answers={},
            summary_draft=SummaryContent(
                chief_complaint="cannot breathe",
                history_of_present_illness=["Synthetic confirmed complaint"],
            ),
            decision="accepted",
            provider="mock",
        ),
        "alert-intake",
    )
    app = FastAPI()
    app.include_router(alerts.router)
    app.dependency_overrides[alerts.get_worklist] = lambda: PostgresIntakeWorklist(pool)
    app.dependency_overrides[alerts.get_alert_repository] = lambda: PostgresAlertRepository(pool)
    monkeypatch.setattr(alerts.settings, "ENABLE_DEMO_ROUTES", True)
    token = create_dev_token(str(doctor), None, "doctor", str(tenant), [str(facility)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        result = await client.post(
            f"/api/v1/alerts/from-intake/{intake.id}?purpose=treatment", json={"reviewed": True}
        )
        assert result.status_code == 200, result.text
        flag = result.json()["alerts"][0]
        repeated = await client.post(
            f"/api/v1/alerts/from-intake/{intake.id}?purpose=treatment", json={"reviewed": True}
        )
        assert repeated.json()["alerts"][0]["id"] == flag["id"]
        for version, action in ((1, "acknowledge"), (2, "resolve")):
            response = await client.post(
                f"/api/v1/alerts/{flag['id']}/commands?purpose=treatment",
                headers={"Idempotency-Key": action},
                json={
                    "action": action,
                    "expected_version": version,
                    **(
                        {"reason_code": "assessed", "rationale": "Synthetic assessment"}
                        if action == "resolve"
                        else {}
                    ),
                },
            )
            assert response.status_code == 200, response.text
        queue = await client.get("/api/v1/alerts?purpose=treatment")
        assert queue.json() == []
        history = await client.get("/api/v1/alerts?purpose=treatment&include_closed=true")
        assert history.json()[0]["lifecycle"]["state"] == "resolved"


async def test_patient_safety_authenticated_consent_replay_and_atomic_evidence(repositories, monkeypatch):
    import json

    import httpx
    from fastapi import FastAPI

    from app.auth.token import create_dev_token
    from app.patient_portal.consent_repository import PostgresPatientConsentRepository
    from app.patient_portal.contracts import PatientConsentCreate
    from app.patient_portal.service import PatientIdentity
    from app.routers import patient_portal
    from app.rules.patient_safety import PatientSafetyService

    pool, _ = repositories
    tenant, patient, facility, encounter = (uuid4() for _ in range(4))
    identity = PatientIdentity(tenant_id=tenant, patient_id=patient, facility_ids={facility})
    consents = PostgresPatientConsentRepository(pool)
    consent = await consents.create(identity, PatientConsentCreate(encounter_id=encounter))
    app = FastAPI()
    app.include_router(patient_portal.router)
    app.dependency_overrides[patient_portal.get_patient_safety_service] = lambda: PatientSafetyService(pool)
    token = create_dev_token(str(patient), None, "patient", str(tenant), [str(facility)])
    body = dict(
        facility_id=str(facility), encounter_id=str(encounter), consent_id=str(consent.id),
        input_version=1, confirmed=True, chief_complaint="cannot breathe and heavy bleeding",
        confirmed_answers={},
    )
    path = "/api/v1/patient-portal/me/safety-confirmations"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        assert (await client.post(path, json=body)).status_code == 401
        client.headers["Authorization"] = f"Bearer {token}"
        for mutation, expected in (
            ({"confirmed": False}, 422), ({"patient_id": str(uuid4())}, 422),
            ({"facility_id": str(uuid4())}, 403), ({"encounter_id": str(uuid4())}, 403),
            ({"consent_id": str(uuid4())}, 403),
        ):
            assert (await client.post(path, json={**body, **mutation})).status_code == expected
        original = PostgresAlertRepository._record
        calls = 0

        async def fail_second(self, *args):
            nonlocal calls
            calls += 1
            await original(*args)
            if calls == 2:
                raise RuntimeError("Injected second alert persistence failure")

        monkeypatch.setattr(PostgresAlertRepository, "_record", fail_second)
        assert (await client.post(path, json=body)).status_code == 500
        assert calls == 2
        async with pool.acquire() as connection:
            async with connection.transaction():
                await PostgresAlertRepository._tenant(connection, tenant)
                for table in ("triage_flag", "triage_flag_history", "triage_outbox"):
                    assert await connection.fetchval(f"SELECT count(*) FROM {table}") == 0
        monkeypatch.setattr(PostgresAlertRepository, "_record", staticmethod(original))
        result = await client.post(path, json=body)
        assert result.status_code == 200, result.text
        assert result.headers["Cache-Control"] == "private, no-store"
        assert result.json()["interrupt_required"] is True
        assert result.json()["durable_alert_count"] == 2
        assert result.json()["staff_acknowledged"] is False
        assert (await client.post(path, json=body)).json() == result.json()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await PostgresAlertRepository._tenant(connection, tenant)
                assert await connection.fetchval("SELECT count(*) FROM triage_flag") == 2
                history = await connection.fetch("SELECT protected_detail FROM triage_flag_history")
                assert len(history) == 2
                assert all(json.loads(row["protected_detail"])["confirmed_sources"]["chief_complaint"] == body["chief_complaint"] for row in history)
                outbox = await connection.fetch("SELECT payload FROM triage_outbox")
                assert len(outbox) == 2
                assert "cannot breathe" not in str(outbox)
                assert "confirmed_sources" not in str(outbox)
        await consents.revoke(identity, consent.id)
        assert (await client.post(path, json=body)).status_code == 403


async def test_timer_ladder_restart_concurrency_scope_and_stale_ack(repositories, monkeypatch):
    from app.rules.alert_timers import AlertTimerWorker, FacilityEscalationPolicy
    from app.rules.policy_registry import PolicyRegistry

    pool, _ = repositories
    tenant, facility, other_facility = uuid4(), uuid4(), uuid4()
    doctor = AlertActor(actor_id=uuid4(), tenant_id=tenant, facility_ids={facility, other_facility}, role="doctor")
    repo = PostgresAlertRepository(pool)
    policy = FacilityEscalationPolicy(
        tenant_id=tenant, facility_id=facility, worker_actor_id=uuid4(),
        policy_id="test-ladder", version="1", owner_reference="synthetic-facility-owner",
        steps=[{"after_seconds": 30}, {"after_seconds": 120}],
    )
    registry = PolicyRegistry(pool)
    operator = uuid4()
    assert await registry.set_active(policy, operator_id=operator, reason_code="test_activation", expected_revision=0) == 1
    rule = evaluate_text_sources({"chief_complaint": "cannot breathe"}).flags[0]

    async def create_flag(scope, age):
        flag = await repo.raise_flag(
            actor=doctor, facility_id=scope, encounter_id=uuid4(),
            evidence=AlertEvidence(input_version=1, fingerprint="f" * 64), rule=rule,
        )
        async with pool.acquire() as connection:
            async with connection.transaction():
                await repo._tenant(connection, tenant)
                await connection.execute(
                    "UPDATE triage_flag SET created_at=now()-$2::INTEGER*INTERVAL '1 second' WHERE id=$1", flag.id, age
                )
        return flag

    due = await create_flag(facility, 180)
    young = await create_flag(facility, 0)
    outside = await create_flag(other_facility, 180)
    worker = AlertTimerWorker(pool, policy)
    await asyncio.gather(worker.run_once(), AlertTimerWorker(pool, policy).run_once())
    # Restart uses persisted step history. Either racing worker may already have
    # advanced step two; repeated scans still stop exactly at the policy limit.
    await AlertTimerWorker(pool, policy).run_once()
    assert await AlertTimerWorker(pool, policy).run_once() == 0
    records = {item["lifecycle"]["id"]: item for item in await repo.list_flags(doctor)}
    assert records[str(due.id)]["lifecycle"]["version"] == 3
    assert records[str(due.id)]["lifecycle"]["owner_role"] == "doctor"
    for untouched in (young, outside):
        assert records[str(untouched.id)]["lifecycle"]["version"] == 1
    async with pool.acquire() as connection:
        async with connection.transaction():
            await repo._tenant(connection, tenant)
            assert await connection.fetchval("SELECT count(*) FROM triage_flag_history WHERE flag_id=$1", due.id) == 3
            assert await connection.fetchval("SELECT count(*) FROM triage_outbox WHERE flag_id=$1", due.id) == 3
            protected = await connection.fetchval("SELECT protected_detail FROM triage_flag_history WHERE flag_id=$1 AND version=2", due.id)
            assert policy.fingerprint in protected
            assert "synthetic-facility-owner" not in str(await connection.fetch("SELECT payload FROM triage_outbox"))

    stale = await create_flag(facility, 180)
    original = worker.repository.command

    async def acknowledge_first(**kwargs):
        await repo.command(
            flag_id=stale.id, actor=doctor, command=AlertCommand(action="acknowledge", expected_version=1), idempotency_key="staff-wins",
        )
        return await original(**kwargs)

    monkeypatch.setattr(worker.repository, "command", acknowledge_first)
    assert await worker.run_once() == 0
    assert await AlertTimerWorker(pool, policy).run_once() == 0
    records = {item["lifecycle"]["id"]: item for item in await repo.list_flags(doctor)}
    assert records[str(stale.id)]["lifecycle"]["state"] == "acknowledged"
    assert records[str(stale.id)]["lifecycle"]["version"] == 2

    with pytest.raises(AlertConflict, match="different content"):
        await registry.set_active(
            policy.model_copy(update={"owner_reference": "changed"}), operator_id=operator,
            reason_code="bad_reuse", expected_revision=1,
        )
    replacement = policy.model_copy(update={"version": "2"})
    assert await registry.set_active(replacement, operator_id=operator, reason_code="replacement", expected_revision=1) == 2
    assert await AlertTimerWorker(pool, policy).run_once() == 0
    with pytest.raises(AlertConflict, match="revision"):
        await registry.set_active(policy, operator_id=operator, reason_code="stale_activation", expected_revision=1)
    assert await registry.set_active(replacement, operator_id=operator, reason_code="pause", expected_revision=2, enabled=False) == 3
    assert await AlertTimerWorker(pool, replacement).run_once() == 0
    assert await registry.set_active(replacement, operator_id=operator, reason_code="resume", expected_revision=3) == 4
    racing_worker = AlertTimerWorker(pool, replacement)
    original_command = racing_worker.repository.command
    switched = False

    async def deactivate_before_commit(**kwargs):
        nonlocal switched
        if not switched:
            await registry.set_active(replacement, operator_id=operator, reason_code="race_pause", expected_revision=4, enabled=False)
            switched = True
        return await original_command(**kwargs)

    monkeypatch.setattr(racing_worker.repository, "command", deactivate_before_commit)
    assert await racing_worker.run_once() == 0
    assert switched
    async with pool.acquire() as connection:
        async with connection.transaction():
            await repo._tenant(connection, tenant)
            assert await connection.fetchval("SELECT count(*) FROM triage_policy_activation_history") == 5
            assert await connection.fetchval("SELECT version FROM triage_flag WHERE id=$1", due.id) == 3
        async with connection.transaction():
            await repo._tenant(connection, uuid4())
            for table in ("triage_policy_artifact", "triage_active_policy", "triage_policy_activation_history"):
                assert await connection.fetchval(f"SELECT count(*) FROM {table}") == 0
        with pytest.raises(asyncpg.RaiseError, match="append-only"):
            async with connection.transaction():
                await repo._tenant(connection, tenant)
                await connection.execute("UPDATE triage_policy_artifact SET policy_version='tampered'")


async def test_outbox_fencing_order_retry_exhaustion_and_replay(repositories):
    from app.rules.alert_outbox import AlertOutbox, encode_event

    pool, schema = repositories
    tenant, facility = uuid4(), uuid4()
    actor = AlertActor(actor_id=uuid4(), tenant_id=tenant, facility_ids={facility}, role="doctor")
    repo = PostgresAlertRepository(pool)
    flag = await repo.raise_flag(
        actor=actor,
        facility_id=facility,
        encounter_id=uuid4(),
        evidence=AlertEvidence(input_version=1, fingerprint="c" * 64),
        rule=evaluate_text_sources({"chief_complaint": "cannot breathe"}).flags[0],
    )
    await repo.command(
        flag_id=flag.id,
        actor=actor,
        command=AlertCommand(action="acknowledge", expected_version=1),
        idempotency_key="ack",
    )
    maintenance = await asyncpg.create_pool(
        DATABASE_URL, min_size=1, max_size=2, server_settings={"search_path": schema}
    )
    try:
        outbox = AlertOutbox(maintenance, max_attempts=2)
        first = (await outbox.claim())[0]
        assert first["flag_version"] == 1
        assert await outbox.claim() == []  # another publisher cannot skip to acknowledgement
        encoded = encode_event(first)
        assert b"cannot breathe" not in encoded and b'"rationale"' not in encoded
        async with maintenance.acquire() as connection:
            await connection.execute(
                "UPDATE triage_outbox SET next_attempt_at=CURRENT_TIMESTAMP WHERE id=$1",
                first["id"],
            )
        replacement = (await outbox.claim())[0]
        assert replacement["id"] == first["id"] and replacement["lease_id"] != first["lease_id"]
        assert await outbox.complete(first) is False
        await outbox.fail(replacement)
        assert (await repo.list_flags(actor))[0]["delivery"] == "failed"
        assert await outbox.claim() == []  # DLQ predecessor blocks later states
        assert await outbox.replay(first["id"]) is True
        replay = (await outbox.claim())[0]
        assert await outbox.complete(replacement) is False
        assert await outbox.complete(replay) is True
        successor = (await outbox.claim())[0]
        assert successor["flag_version"] == 2
        assert await outbox.complete(successor) is True
        assert (await repo.list_flags(actor))[0]["delivery"] == "broker_published"
        assert await outbox.claim() == []
        assert await outbox.replay(first["id"]) is False
    finally:
        await maintenance.close()


async def test_outbox_publish_failure_leaves_retryable_row(repositories):
    from unittest.mock import AsyncMock

    from app.rules.alert_outbox import AlertOutbox, publish_once

    pool, schema = repositories
    tenant, facility = uuid4(), uuid4()
    actor = AlertActor(actor_id=uuid4(), tenant_id=tenant, facility_ids={facility}, role="doctor")
    await PostgresAlertRepository(pool).raise_flag(
        actor=actor,
        facility_id=facility,
        encounter_id=uuid4(),
        evidence=AlertEvidence(input_version=1, fingerprint="d" * 64),
        rule=evaluate_text_sources({"chief_complaint": "cannot breathe"}).flags[0],
    )
    maintenance = await asyncpg.create_pool(
        DATABASE_URL, min_size=1, max_size=2, server_settings={"search_path": schema}
    )
    try:
        outbox = AlertOutbox(maintenance)
        producer = AsyncMock()
        producer.send_and_wait.side_effect = RuntimeError("private broker credential")
        assert await publish_once(outbox, producer, "synthetic.triage") == 0
        async with maintenance.acquire() as connection:
            row = await connection.fetchrow("SELECT * FROM triage_outbox")
            assert row["published_at"] is None and row["attempts"] == 1
            assert row["last_error_class"] == "transport_error"
            await connection.execute("UPDATE triage_outbox SET next_attempt_at=CURRENT_TIMESTAMP")
        producer.send_and_wait.side_effect = None
        assert await publish_once(outbox, producer, "synthetic.triage") == 1
        assert producer.send_and_wait.call_args.args[0] == "synthetic.triage"
    finally:
        await maintenance.close()

@pytest.mark.skipif(os.getenv("TRIAGE_KAFKA_INTEGRATION") != "1", reason="Enable TRIAGE_KAFKA_INTEGRATION with local Kafka")
async def test_real_alert_outbox_reaches_kafka_with_stable_identity(repositories):
    import json

    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    from aiokafka.admin import AIOKafkaAdminClient

    from app.rules.alert_outbox import AlertOutbox, publish_once
    pool, schema = repositories
    tenant, facility = uuid4(), uuid4()
    actor = AlertActor(actor_id=uuid4(), tenant_id=tenant, facility_ids={facility}, role="doctor")
    flag = await PostgresAlertRepository(pool).raise_flag(actor=actor, facility_id=facility, encounter_id=uuid4(),
        evidence=AlertEvidence(input_version=1, fingerprint="e" * 64),
        rule=evaluate_text_sources({"chief_complaint":"cannot breathe"}).flags[0])
    maintenance = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2, server_settings={"search_path":schema})
    brokers = os.getenv("TEST_KAFKA_BROKERS", "127.0.0.1:9092")
    topic = f"triage-test-{uuid4().hex}"
    producer = AIOKafkaProducer(bootstrap_servers=brokers, acks="all", enable_idempotence=True)
    consumer = AIOKafkaConsumer(topic, bootstrap_servers=brokers, group_id=topic, auto_offset_reset="earliest", enable_auto_commit=False)
    admin = AIOKafkaAdminClient(bootstrap_servers=brokers)
    try:
        await producer.start()
        assert await publish_once(AlertOutbox(maintenance), producer, topic) == 1
        await consumer.start()
        message = await asyncio.wait_for(consumer.getone(), timeout=20)
        decoded = json.loads(message.value)
        assert message.key == str(flag.id).encode()
        assert decoded["aggregate_id"] == str(flag.id)
        assert decoded["tenant_id"] == str(tenant)
        assert decoded["event_type"] == "CriticalAlertRaised.v1"
        assert "cannot breathe" not in message.value.decode()
        async with maintenance.acquire() as connection:
            row = await connection.fetchrow("SELECT id,published_at FROM triage_outbox")
            assert decoded["event_id"] == str(row["id"])
            assert row["published_at"] is not None
    finally:
        await consumer.stop()
        await producer.stop()
        await maintenance.close()
        await admin.start()
        try:
            await admin.delete_topics([topic])
        finally:
            await admin.close()
