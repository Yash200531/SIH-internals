import json
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.patient_portal.contracts import PatientConsentCreate, PatientConsentResponse
from app.patient_portal.service import PatientIdentity

_INSERT = """
INSERT INTO consent_artifact (
    id, tenant_id, patient_id, encounter_id, purpose, scope, status,
    granted_at, expires_at, version, created_at, updated_at
) VALUES ($1, $2, $3, $4, 'treatment', $5::JSONB, 'granted', $6, $7, 1, $6, $6)
RETURNING id, patient_id, encounter_id, purpose, scope, status, granted_at,
          expires_at, revoked_at, version
"""

_LIST = """
SELECT id, patient_id, encounter_id, purpose, scope, status, granted_at,
       expires_at, revoked_at, version
FROM consent_artifact
WHERE tenant_id = $1 AND patient_id = $2
ORDER BY granted_at DESC, id
LIMIT $3
"""

_REVOKE = """
UPDATE consent_artifact
SET status = 'revoked', revoked_at = $4, updated_at = $4, version = version + 1
WHERE tenant_id = $1 AND patient_id = $2 AND id = $3 AND status = 'granted'
RETURNING id, patient_id, encounter_id, purpose, scope, status, granted_at,
          expires_at, revoked_at, version
"""


class PatientConsentNotFound(Exception):
    pass


class PatientConsentRepository(Protocol):
    async def create(
        self, identity: PatientIdentity, command: PatientConsentCreate
    ) -> PatientConsentResponse: ...

    async def list_for_patient(
        self, identity: PatientIdentity, *, limit: int = 100
    ) -> list[PatientConsentResponse]: ...

    async def revoke(
        self, identity: PatientIdentity, consent_id: UUID
    ) -> PatientConsentResponse: ...


class InMemoryPatientConsentRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[UUID, UUID], PatientConsentResponse] = {}

    async def create(
        self, identity: PatientIdentity, command: PatientConsentCreate
    ) -> PatientConsentResponse:
        now = datetime.now(UTC)
        consent = PatientConsentResponse(
            id=uuid4(),
            patient_id=identity.patient_id,
            encounter_id=command.encounter_id,
            purpose="treatment",
            scope={
                "document_upload": command.document_upload,
                "audio_retention": command.retain_audio,
            },
            status="granted",
            granted_at=now,
            expires_at=now + timedelta(hours=command.expires_in_hours),
            revoked_at=None,
            version=1,
        )
        self._items[(identity.tenant_id, consent.id)] = consent
        return consent.model_copy(deep=True)

    async def list_for_patient(
        self, identity: PatientIdentity, *, limit: int = 100
    ) -> list[PatientConsentResponse]:
        return [
            item.model_copy(deep=True)
            for (tenant_id, _), item in self._items.items()
            if tenant_id == identity.tenant_id and item.patient_id == identity.patient_id
        ][:limit]

    async def revoke(
        self, identity: PatientIdentity, consent_id: UUID
    ) -> PatientConsentResponse:
        item = self._items.get((identity.tenant_id, consent_id))
        if item is None or item.patient_id != identity.patient_id or item.status != "granted":
            raise PatientConsentNotFound("Consent not found")
        revoked = item.model_copy(
            update={
                "status": "revoked",
                "revoked_at": datetime.now(UTC),
                "version": item.version + 1,
            }
        )
        self._items[(identity.tenant_id, consent_id)] = revoked
        return revoked.model_copy(deep=True)


class PostgresPatientConsentRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def create(
        self, identity: PatientIdentity, command: PatientConsentCreate
    ) -> PatientConsentResponse:
        now = datetime.now(UTC)
        scope = {
            "document_upload": command.document_upload,
            "audio_retention": command.retain_audio,
        }
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, identity.tenant_id)
                row = await connection.fetchrow(
                    _INSERT,
                    uuid4(),
                    identity.tenant_id,
                    identity.patient_id,
                    command.encounter_id,
                    json.dumps(scope),
                    now,
                    now + timedelta(hours=command.expires_in_hours),
                )
        return self._record(row)

    async def list_for_patient(
        self, identity: PatientIdentity, *, limit: int = 100
    ) -> list[PatientConsentResponse]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, identity.tenant_id)
                rows = await connection.fetch(
                    _LIST, identity.tenant_id, identity.patient_id, limit
                )
        return [self._record(row) for row in rows]

    async def revoke(
        self, identity: PatientIdentity, consent_id: UUID
    ) -> PatientConsentResponse:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, identity.tenant_id)
                row = await connection.fetchrow(
                    _REVOKE,
                    identity.tenant_id,
                    identity.patient_id,
                    consent_id,
                    datetime.now(UTC),
                )
        if row is None:
            raise PatientConsentNotFound("Consent not found")
        return self._record(row)

    @staticmethod
    async def _set_tenant(connection: Any, tenant_id: UUID) -> None:
        await connection.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))

    @staticmethod
    def _record(row: Any) -> PatientConsentResponse:
        values = dict(row)
        if isinstance(values["scope"], str):
            values["scope"] = json.loads(values["scope"])
        return PatientConsentResponse.model_validate(values)
