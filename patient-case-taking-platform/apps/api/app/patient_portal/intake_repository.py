import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.patient_portal.contracts import (
    PatientIntakeSubmissionCreate,
    PatientIntakeSubmissionResponse,
)
from app.patient_portal.service import PatientIdentity

_INSERT = """
INSERT INTO patient_intake_submission (
    id, tenant_id, facility_id, patient_id, encounter_id, session_id,
    consent_id, language, chief_complaint, confirmed_answers, summary_draft,
    decision, provider, idempotency_key, request_hash_sha256, created_at
)
SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10::JSONB, $11::JSONB,
       $12, $13, $14, $15, $16
FROM consent_artifact
WHERE tenant_id = $2 AND id = $7 AND patient_id = $4 AND encounter_id = $5
  AND purpose = 'treatment' AND status = 'granted'
  AND (expires_at IS NULL OR expires_at > $16)
ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
RETURNING id, patient_id, encounter_id, session_id, consent_id, decision,
          provider, created_at
"""

_GET_IDEMPOTENT = """
SELECT id, patient_id, encounter_id, session_id, consent_id, decision,
       provider, created_at, request_hash_sha256
FROM patient_intake_submission
WHERE tenant_id = $1 AND idempotency_key = $2 AND patient_id = $3
"""


class PatientIntakeConflict(Exception):
    pass


class PatientIntakeAuthorizationDenied(Exception):
    pass


class PatientIntakeRepository(Protocol):
    async def create(
        self,
        identity: PatientIdentity,
        command: PatientIntakeSubmissionCreate,
        idempotency_key: str,
    ) -> PatientIntakeSubmissionResponse: ...


class InMemoryPatientIntakeRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[UUID, str], tuple[str, PatientIntakeSubmissionResponse]] = {}

    async def create(
        self,
        identity: PatientIdentity,
        command: PatientIntakeSubmissionCreate,
        idempotency_key: str,
    ) -> PatientIntakeSubmissionResponse:
        request_hash = _request_hash(command)
        existing = self._items.get((identity.tenant_id, idempotency_key))
        if existing:
            if existing[0] != request_hash:
                raise PatientIntakeConflict("Idempotency key conflict")
            return existing[1].model_copy(deep=True)
        response = PatientIntakeSubmissionResponse(
            id=uuid4(),
            patient_id=identity.patient_id,
            encounter_id=command.encounter_id,
            session_id=command.session_id,
            consent_id=command.consent_id,
            decision=command.decision,
            provider=command.provider,
            created_at=datetime.now(UTC),
        )
        self._items[(identity.tenant_id, idempotency_key)] = (request_hash, response)
        return response.model_copy(deep=True)


class PostgresPatientIntakeRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def create(
        self,
        identity: PatientIdentity,
        command: PatientIntakeSubmissionCreate,
        idempotency_key: str,
    ) -> PatientIntakeSubmissionResponse:
        if command.facility_id not in identity.facility_ids:
            raise PatientIntakeAuthorizationDenied
        request_hash = _request_hash(command)
        created_at = datetime.now(UTC)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true)",
                    str(identity.tenant_id),
                )
                row = await connection.fetchrow(
                    _INSERT,
                    uuid4(),
                    identity.tenant_id,
                    command.facility_id,
                    identity.patient_id,
                    command.encounter_id,
                    command.session_id,
                    command.consent_id,
                    command.language,
                    command.chief_complaint,
                    json.dumps(command.confirmed_answers, sort_keys=True),
                    command.summary_draft.model_dump_json(),
                    command.decision,
                    command.provider,
                    idempotency_key,
                    request_hash,
                    created_at,
                )
                if row is None:
                    existing = await connection.fetchrow(
                        _GET_IDEMPOTENT,
                        identity.tenant_id,
                        idempotency_key,
                        identity.patient_id,
                    )
                    if existing is None:
                        raise PatientIntakeAuthorizationDenied
                    if existing["request_hash_sha256"] != request_hash:
                        raise PatientIntakeConflict("Idempotency key conflict")
                    row = existing
        return PatientIntakeSubmissionResponse.model_validate(dict(row))


def _request_hash(command: PatientIntakeSubmissionCreate) -> str:
    payload = command.model_dump_json(exclude_none=False)
    return hashlib.sha256(payload.encode()).hexdigest()
