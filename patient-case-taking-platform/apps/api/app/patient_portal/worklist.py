"""Staff handoff projection owned by the patient intake boundary."""

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class IntakeHandoff(BaseModel):
    id: UUID
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    language: Literal["hi", "en"]
    chief_complaint: str
    confirmed_answers: dict[str, str]
    created_at: datetime
    context_version: int | None


_READ = """
SELECT i.id, i.facility_id, i.patient_id, i.encounter_id, i.language,
       i.chief_complaint, i.confirmed_answers, i.created_at, s.version AS context_version
FROM patient_intake_submission i
JOIN consent_artifact c ON c.tenant_id = i.tenant_id AND c.id = i.consent_id
  AND c.patient_id = i.patient_id AND c.encounter_id = i.encounter_id
LEFT JOIN confirmed_encounter_summary_context s
  ON s.tenant_id = i.tenant_id AND s.encounter_id = i.encounter_id
  AND s.patient_id = i.patient_id AND s.facility_id = i.facility_id
WHERE i.tenant_id = $1 AND i.facility_id = ANY($2::UUID[])
  AND i.decision = 'accepted' AND c.purpose = 'treatment' AND c.status = 'granted'
  AND (c.expires_at IS NULL OR c.expires_at > CURRENT_TIMESTAMP)
  AND ($3::UUID IS NULL OR i.id = $3)
ORDER BY i.created_at DESC, i.id
LIMIT $4 OFFSET $5
"""


class PostgresIntakeWorklist:
    def __init__(self, pool: Any):
        self._pool = pool

    async def read(
        self, tenant_id: UUID, facilities: set[UUID], *,
        intake_id: UUID | None = None, limit: int = 50, offset: int = 0,
    ) -> list[IntakeHandoff]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id),
                )
                rows = await connection.fetch(
                    _READ, tenant_id, list(facilities), intake_id, limit, offset,
                )
        result = []
        for row in rows:
            data = dict(row)
            if isinstance(data["confirmed_answers"], str):
                data["confirmed_answers"] = json.loads(data["confirmed_answers"])
            result.append(IntakeHandoff.model_validate(data))
        return result
