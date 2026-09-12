"""Durable metadata-only audit records for clinical retrieval."""

import json
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ClinicalSearchAuditRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    patient_id: UUID
    actor_id: UUID
    actor_role: str = Field(pattern="^(patient|doctor|nurse)$")
    action: str = Field(pattern="^(search|timeline|fhir_search|export)$")
    purpose: str = Field(default="treatment", pattern="^treatment$")
    authorized_facility_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    query_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    filter_metadata: dict[str, object] = Field(default_factory=dict)
    result_count: int | None = Field(default=None, ge=0)
    latency_ms: int = Field(ge=0)
    outcome: str = Field(pattern="^(success|unavailable|error)$")
    correlation_id: UUID
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ClinicalSearchAuditRepository(Protocol):
    async def record(self, entry: ClinicalSearchAuditRecord) -> None: ...


class PostgresClinicalSearchAuditRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def record(self, entry: ClinicalSearchAuditRecord) -> None:
        metadata = json.dumps(entry.filter_metadata, sort_keys=True, separators=(",", ":"))
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true)",
                    str(entry.tenant_id),
                )
                await connection.execute(
                    """
                    INSERT INTO clinical_search_audit (
                        id, tenant_id, patient_id, actor_id, actor_role, action,
                        purpose, authorized_facility_ids, query_sha256,
                        filter_metadata, result_count, latency_ms, outcome,
                        correlation_id, occurred_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8::UUID[], $9,
                        $10::JSONB, $11, $12, $13, $14, $15
                    )
                    """,
                    entry.id,
                    entry.tenant_id,
                    entry.patient_id,
                    entry.actor_id,
                    entry.actor_role,
                    entry.action,
                    entry.purpose,
                    list(entry.authorized_facility_ids),
                    entry.query_sha256,
                    metadata,
                    entry.result_count,
                    entry.latency_ms,
                    entry.outcome,
                    entry.correlation_id,
                    entry.occurred_at,
                )


class InMemoryClinicalSearchAuditRepository:
    def __init__(self) -> None:
        self.entries: list[ClinicalSearchAuditRecord] = []

    async def record(self, entry: ClinicalSearchAuditRecord) -> None:
        self.entries.append(entry.model_copy(deep=True))
