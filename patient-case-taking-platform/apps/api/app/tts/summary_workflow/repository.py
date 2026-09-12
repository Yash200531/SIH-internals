"""Repository boundary and in-memory reference implementation for Phase 8."""

import json
from collections import defaultdict
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.summary_workflow.contracts import SummaryAction, SummaryRecord, SummaryStatus


class SummaryNotFound(Exception):
    pass


class SummaryConflict(Exception):
    pass


class SummaryRepository(Protocol):
    async def create(
        self, *, record: SummaryRecord, action: SummaryAction, idempotency_key: str,
        request_hash_sha256: str
    ) -> SummaryRecord: ...

    async def get(self, *, tenant_id: UUID, summary_id: UUID) -> SummaryRecord: ...

    async def list_for_encounter(
        self, *, tenant_id: UUID, encounter_id: UUID
    ) -> list[SummaryRecord]: ...

    async def list_signed_for_patient(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
        limit: int = 100,
    ) -> list[SummaryRecord]: ...

    async def count_signed_for_patient(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
    ) -> int: ...

    async def replace(
        self, *, record: SummaryRecord, action: SummaryAction, expected_version: int
    ) -> SummaryRecord: ...

    async def history(
        self, *, tenant_id: UUID, summary_id: UUID
    ) -> list[SummaryAction]: ...

    async def find_idempotent(
        self, *, tenant_id: UUID, idempotency_key: str, request_hash_sha256: str
    ) -> SummaryRecord | None: ...

    async def regenerate(
        self, *, previous: SummaryRecord, replacement: SummaryRecord,
        previous_action: SummaryAction, replacement_action: SummaryAction,
        expected_version: int, idempotency_key: str, request_hash_sha256: str
    ) -> SummaryRecord: ...


class InMemorySummaryRepository:
    """Tenant-scoped repository used by domain and HTTP contract tests."""

    def __init__(self) -> None:
        self._records: dict[tuple[UUID, UUID], SummaryRecord] = {}
        self._actions: dict[tuple[UUID, UUID], list[SummaryAction]] = defaultdict(list)
        self._idempotency: dict[tuple[UUID, str], tuple[UUID, str]] = {}

    async def create(
        self, *, record: SummaryRecord, action: SummaryAction, idempotency_key: str,
        request_hash_sha256: str
    ) -> SummaryRecord:
        replay = await self.find_idempotent(
            tenant_id=record.tenant_id, idempotency_key=idempotency_key,
            request_hash_sha256=request_hash_sha256,
        )
        if replay is not None:
            return replay
        key = (record.tenant_id, record.id)
        if key in self._records:
            raise SummaryConflict("Summary already exists")
        self._records[key] = record.model_copy(deep=True)
        self._actions[key].append(action.model_copy(deep=True))
        self._idempotency[(record.tenant_id, idempotency_key)] = (
            record.id, request_hash_sha256
        )
        return record.model_copy(deep=True)

    async def get(self, *, tenant_id: UUID, summary_id: UUID) -> SummaryRecord:
        record = self._records.get((tenant_id, summary_id))
        if record is None:
            raise SummaryNotFound("Summary not found")
        return record.model_copy(deep=True)

    async def list_for_encounter(
        self, *, tenant_id: UUID, encounter_id: UUID
    ) -> list[SummaryRecord]:
        records = [
            record.model_copy(deep=True)
            for (record_tenant, _), record in self._records.items()
            if record_tenant == tenant_id and record.encounter_id == encounter_id
        ]
        return sorted(records, key=lambda item: (item.generation, item.created_at))

    async def list_signed_for_patient(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
        limit: int = 100,
    ) -> list[SummaryRecord]:
        if not facility_ids or not 1 <= limit <= 200:
            return []
        records = [
            record.model_copy(deep=True)
            for (record_tenant, _), record in self._records.items()
            if record_tenant == tenant_id
            and record.patient_id == patient_id
            and record.facility_id in facility_ids
            and record.status is SummaryStatus.SIGNED
        ]
        return sorted(records, key=lambda item: item.signed_at or item.updated_at, reverse=True)[
            :limit
        ]

    async def count_signed_for_patient(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
    ) -> int:
        return sum(
            1
            for (record_tenant, _), record in self._records.items()
            if record_tenant == tenant_id
            and record.patient_id == patient_id
            and record.facility_id in facility_ids
            and record.status is SummaryStatus.SIGNED
        )

    async def replace(
        self, *, record: SummaryRecord, action: SummaryAction, expected_version: int
    ) -> SummaryRecord:
        key = (record.tenant_id, record.id)
        current = self._records.get(key)
        if current is None:
            raise SummaryNotFound("Summary not found")
        if current.lock_version != expected_version:
            raise SummaryConflict("Summary version is stale")
        self._records[key] = record.model_copy(deep=True)
        self._actions[key].append(action.model_copy(deep=True))
        return record.model_copy(deep=True)

    async def history(
        self, *, tenant_id: UUID, summary_id: UUID
    ) -> list[SummaryAction]:
        await self.get(tenant_id=tenant_id, summary_id=summary_id)
        return [item.model_copy(deep=True) for item in self._actions[(tenant_id, summary_id)]]

    async def find_idempotent(
        self, *, tenant_id: UUID, idempotency_key: str, request_hash_sha256: str
    ) -> SummaryRecord | None:
        replay = self._idempotency.get((tenant_id, idempotency_key))
        if replay is None:
            return None
        summary_id, stored_hash = replay
        if stored_hash != request_hash_sha256:
            raise SummaryConflict("Idempotency key was already used for another request")
        return await self.get(tenant_id=tenant_id, summary_id=summary_id)

    async def regenerate(
        self, *, previous: SummaryRecord, replacement: SummaryRecord,
        previous_action: SummaryAction, replacement_action: SummaryAction,
        expected_version: int, idempotency_key: str, request_hash_sha256: str
    ) -> SummaryRecord:
        replay = await self.find_idempotent(
            tenant_id=previous.tenant_id, idempotency_key=idempotency_key,
            request_hash_sha256=request_hash_sha256,
        )
        if replay is not None:
            return replay
        key = (previous.tenant_id, previous.id)
        current = self._records.get(key)
        if current is None:
            raise SummaryNotFound("Summary not found")
        if current.lock_version != expected_version:
            raise SummaryConflict("Summary version is stale")
        self._records[key] = previous.model_copy(deep=True)
        self._actions[key].append(previous_action.model_copy(deep=True))
        replacement_key = (replacement.tenant_id, replacement.id)
        self._records[replacement_key] = replacement.model_copy(deep=True)
        self._actions[replacement_key].append(replacement_action.model_copy(deep=True))
        self._idempotency[(replacement.tenant_id, idempotency_key)] = (
            replacement.id, request_hash_sha256
        )
        return replacement.model_copy(deep=True)


_INSERT_SUMMARY = """
INSERT INTO clinical_summary_workflow (
    id, tenant_id, facility_id, patient_id, encounter_id, lineage_id,
    generation, parent_summary_id, status, content, evidence, confidence,
    provider, schema_version, degraded, lock_version, created_by_actor_id,
    created_at, updated_at, signed_by_actor_id, signed_at, signature_sha256,
    rejection_reason, idempotency_key, request_hash_sha256
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10::JSONB, $11::JSONB,
    $12::JSONB, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22,
    $23, $24, $25
)
ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
RETURNING *
"""

_GET_SUMMARY = """
SELECT * FROM clinical_summary_workflow WHERE tenant_id = $1 AND id = $2
"""

_GET_IDEMPOTENT = """
SELECT * FROM clinical_summary_workflow
WHERE tenant_id = $1 AND idempotency_key = $2
"""

_LIST_SUMMARIES = """
SELECT * FROM clinical_summary_workflow
WHERE tenant_id = $1 AND encounter_id = $2
ORDER BY generation, created_at
"""

_LIST_SIGNED_FOR_PATIENT = """
SELECT * FROM clinical_summary_workflow
WHERE tenant_id = $1
  AND patient_id = $2
  AND facility_id = ANY($3::UUID[])
  AND status = 'signed'
ORDER BY signed_at DESC, id
LIMIT $4
"""

_COUNT_SIGNED_FOR_PATIENT = """
SELECT COUNT(*) FROM clinical_summary_workflow
WHERE tenant_id = $1
  AND patient_id = $2
  AND facility_id = ANY($3::UUID[])
  AND status = 'signed'
"""

_UPDATE_SUMMARY = """
UPDATE clinical_summary_workflow SET
    status = $4, content = $5::JSONB, evidence = $6::JSONB,
    confidence = $7::JSONB, provider = $8, degraded = $9,
    lock_version = $10, updated_at = $11, signed_by_actor_id = $12,
    signed_at = $13, signature_sha256 = $14, rejection_reason = $15
WHERE tenant_id = $1 AND id = $2 AND lock_version = $3
RETURNING *
"""

_INSERT_ACTION = """
INSERT INTO clinical_summary_action (
    id, tenant_id, summary_id, actor_id, actor_role, action, from_status,
    to_status, resulting_lock_version, metadata, occurred_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::JSONB, $11)
"""

_GET_HISTORY = """
SELECT * FROM clinical_summary_action
WHERE tenant_id = $1 AND summary_id = $2
ORDER BY occurred_at, id
"""

_INSERT_OUTBOX = """
INSERT INTO clinical_summary_outbox (
    event_id, tenant_id, summary_id, event_type, idempotency_key, payload
) VALUES ($1, $2, $3, $4, $5, $6::JSONB)
"""


class PostgresSummaryRepository:
    """Durable summary state with transaction-local tenant RLS context."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def create(
        self, *, record: SummaryRecord, action: SummaryAction, idempotency_key: str,
        request_hash_sha256: str
    ) -> SummaryRecord:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, record.tenant_id)
                row = await connection.fetchrow(
                    _INSERT_SUMMARY,
                    record.id, record.tenant_id, record.facility_id, record.patient_id,
                    record.encounter_id, record.lineage_id, record.generation,
                    record.parent_summary_id, record.status.value,
                    _json(record.content), _json(record.evidence), _json(record.confidence),
                    record.provider, record.schema_version, record.degraded,
                    record.lock_version, record.created_by_actor_id, record.created_at,
                    record.updated_at, record.signed_by_actor_id, record.signed_at,
                    record.signature_sha256, record.rejection_reason, idempotency_key,
                    request_hash_sha256,
                )
                if row is None:
                    replay = await connection.fetchrow(
                        _GET_IDEMPOTENT, record.tenant_id, idempotency_key
                    )
                    if replay is None:
                        raise SummaryConflict("Summary creation conflicted")
                    if replay["request_hash_sha256"] != request_hash_sha256:
                        raise SummaryConflict(
                            "Idempotency key was already used for another request"
                        )
                    return self._record(replay)
                await self._insert_action(connection, action)
                await self._insert_outbox(connection, action)
        return self._record(row)

    async def get(self, *, tenant_id: UUID, summary_id: UUID) -> SummaryRecord:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                row = await connection.fetchrow(_GET_SUMMARY, tenant_id, summary_id)
        if row is None:
            raise SummaryNotFound("Summary not found")
        return self._record(row)

    async def list_for_encounter(
        self, *, tenant_id: UUID, encounter_id: UUID
    ) -> list[SummaryRecord]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                rows = await connection.fetch(_LIST_SUMMARIES, tenant_id, encounter_id)
        return [self._record(row) for row in rows]

    async def list_signed_for_patient(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
        limit: int = 100,
    ) -> list[SummaryRecord]:
        if not facility_ids or not 1 <= limit <= 200:
            return []
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                rows = await connection.fetch(
                    _LIST_SIGNED_FOR_PATIENT,
                    tenant_id,
                    patient_id,
                    list(facility_ids),
                    limit,
                )
        return [self._record(row) for row in rows]

    async def count_signed_for_patient(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
    ) -> int:
        if not facility_ids:
            return 0
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                count = await connection.fetchval(
                    _COUNT_SIGNED_FOR_PATIENT,
                    tenant_id,
                    patient_id,
                    list(facility_ids),
                )
        return int(count or 0)

    async def replace(
        self, *, record: SummaryRecord, action: SummaryAction, expected_version: int
    ) -> SummaryRecord:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, record.tenant_id)
                row = await connection.fetchrow(
                    _UPDATE_SUMMARY,
                    record.tenant_id, record.id, expected_version, record.status.value,
                    _json(record.content), _json(record.evidence), _json(record.confidence),
                    record.provider, record.degraded, record.lock_version,
                    record.updated_at, record.signed_by_actor_id, record.signed_at,
                    record.signature_sha256, record.rejection_reason,
                )
                if row is None:
                    visible = await connection.fetchrow(
                        _GET_SUMMARY, record.tenant_id, record.id
                    )
                    if visible is None:
                        raise SummaryNotFound("Summary not found")
                    raise SummaryConflict("Summary version is stale")
                await self._insert_action(connection, action)
                await self._insert_outbox(connection, action)
        return self._record(row)

    async def history(
        self, *, tenant_id: UUID, summary_id: UUID
    ) -> list[SummaryAction]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                if await connection.fetchrow(_GET_SUMMARY, tenant_id, summary_id) is None:
                    raise SummaryNotFound("Summary not found")
                rows = await connection.fetch(_GET_HISTORY, tenant_id, summary_id)
        return [self._action(row) for row in rows]

    async def find_idempotent(
        self, *, tenant_id: UUID, idempotency_key: str, request_hash_sha256: str
    ) -> SummaryRecord | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                row = await connection.fetchrow(
                    _GET_IDEMPOTENT, tenant_id, idempotency_key
                )
        if row is None:
            return None
        if row["request_hash_sha256"] != request_hash_sha256:
            raise SummaryConflict("Idempotency key was already used for another request")
        return self._record(row)

    async def regenerate(
        self, *, previous: SummaryRecord, replacement: SummaryRecord,
        previous_action: SummaryAction, replacement_action: SummaryAction,
        expected_version: int, idempotency_key: str, request_hash_sha256: str
    ) -> SummaryRecord:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, previous.tenant_id)
                replay = await connection.fetchrow(
                    _GET_IDEMPOTENT, previous.tenant_id, idempotency_key
                )
                if replay is not None:
                    if replay["request_hash_sha256"] != request_hash_sha256:
                        raise SummaryConflict(
                            "Idempotency key was already used for another request"
                        )
                    return self._record(replay)
                prior_row = await connection.fetchrow(
                    _UPDATE_SUMMARY, previous.tenant_id, previous.id,
                    expected_version, previous.status.value, _json(previous.content),
                    _json(previous.evidence), _json(previous.confidence),
                    previous.provider, previous.degraded, previous.lock_version,
                    previous.updated_at, previous.signed_by_actor_id,
                    previous.signed_at, previous.signature_sha256,
                    previous.rejection_reason,
                )
                if prior_row is None:
                    # A concurrent identical request may have completed while this
                    # transaction waited on the previous row lock.
                    replay = await connection.fetchrow(
                        _GET_IDEMPOTENT, previous.tenant_id, idempotency_key
                    )
                    if replay is not None and replay["request_hash_sha256"] == request_hash_sha256:
                        return self._record(replay)
                    visible = await connection.fetchrow(
                        _GET_SUMMARY, previous.tenant_id, previous.id
                    )
                    if visible is None:
                        raise SummaryNotFound("Summary not found")
                    raise SummaryConflict("Summary version is stale")
                row = await connection.fetchrow(
                    _INSERT_SUMMARY,
                    replacement.id, replacement.tenant_id, replacement.facility_id,
                    replacement.patient_id, replacement.encounter_id,
                    replacement.lineage_id, replacement.generation,
                    replacement.parent_summary_id, replacement.status.value,
                    _json(replacement.content), _json(replacement.evidence),
                    _json(replacement.confidence), replacement.provider,
                    replacement.schema_version, replacement.degraded,
                    replacement.lock_version, replacement.created_by_actor_id,
                    replacement.created_at, replacement.updated_at,
                    replacement.signed_by_actor_id, replacement.signed_at,
                    replacement.signature_sha256, replacement.rejection_reason,
                    idempotency_key, request_hash_sha256,
                )
                if row is None:
                    raise SummaryConflict("Summary regeneration conflicted")
                await self._insert_action(connection, previous_action)
                await self._insert_outbox(connection, previous_action)
                await self._insert_action(connection, replacement_action)
                await self._insert_outbox(connection, replacement_action)
        return self._record(row)

    @staticmethod
    async def _set_tenant(connection: Any, tenant_id: UUID) -> None:
        await connection.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))

    @staticmethod
    async def _insert_action(connection: Any, action: SummaryAction) -> None:
        await connection.execute(
            _INSERT_ACTION, action.id, action.tenant_id, action.summary_id,
            action.actor_id, action.actor_role, action.action,
            action.from_status.value if action.from_status else None,
            action.to_status.value, action.resulting_lock_version,
            _json(action.metadata), action.occurred_at,
        )

    @staticmethod
    async def _insert_outbox(connection: Any, action: SummaryAction) -> None:
        await connection.execute(
            _INSERT_OUTBOX, uuid4(), action.tenant_id, action.summary_id,
            f"clinical.summary.{action.action}.v1",
            f"{action.summary_id}:{action.resulting_lock_version}:{action.action}",
            json.dumps({
                "summary_id": str(action.summary_id),
                "status": action.to_status.value,
                "lock_version": action.resulting_lock_version,
                "actor_role": action.actor_role,
            }),
        )

    @staticmethod
    def _record(row: Any) -> SummaryRecord:
        values = dict(row)
        values["content"] = _decoded(values["content"])
        values["evidence"] = _decoded(values["evidence"])
        values["confidence"] = _decoded(values["confidence"])
        values.pop("idempotency_key", None)
        return SummaryRecord.model_validate(values)

    @staticmethod
    def _action(row: Any) -> SummaryAction:
        values = dict(row)
        values["metadata"] = _decoded(values["metadata"])
        return SummaryAction.model_validate(values)


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in value]
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _decoded(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value
