"""Authoritative, clinician-confirmed source assembly for Phase 8."""

import json
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from app.rules.triage import detect_red_flags
from app.summary_workflow.contracts import (
    ConfirmedEncounterContext,
    ConfirmEncounterContextCommand,
    SummarySourceBundle,
)
from app.summary_workflow.repository import SummaryConflict, SummaryNotFound


class SummaryContextRepository(Protocol):
    async def confirm(
        self, *, tenant_id: UUID, actor_id: UUID, command: ConfirmEncounterContextCommand
    ) -> ConfirmedEncounterContext: ...

    async def assemble(
        self,
        *,
        tenant_id: UUID,
        facility_id: UUID,
        patient_id: UUID,
        encounter_id: UUID,
        language: Literal["hi", "en"],
    ) -> SummarySourceBundle: ...


class InMemorySummaryContextRepository:
    def __init__(self) -> None:
        self._contexts: dict[tuple[UUID, UUID], ConfirmedEncounterContext] = {}
        self._document_facts: dict[tuple[UUID, UUID], list[tuple[UUID, str]]] = {}

    async def confirm(
        self, *, tenant_id: UUID, actor_id: UUID, command: ConfirmEncounterContextCommand
    ) -> ConfirmedEncounterContext:
        key = (tenant_id, command.encounter_id)
        previous = self._contexts.get(key)
        if previous is None and command.expected_version is not None:
            raise SummaryConflict("Confirmed context version is stale")
        if previous is not None and previous.version != command.expected_version:
            raise SummaryConflict("Confirmed context version is stale")
        if previous is not None and (
            previous.facility_id != command.facility_id or previous.patient_id != command.patient_id
        ):
            raise SummaryConflict("Confirmed context identity cannot change")
        flags = _deterministic_flags(command.chief_complaint, command.confirmed_answers)
        context = ConfirmedEncounterContext(
            tenant_id=tenant_id,
            **command.model_dump(exclude={"expected_version"}),
            deterministic_red_flags=flags,
            confirmed_by_actor_id=actor_id,
            confirmed_at=datetime.now(UTC),
            version=1 if previous is None else previous.version + 1,
        )
        self._contexts[key] = context
        return context.model_copy(deep=True)

    async def assemble(
        self,
        *,
        tenant_id: UUID,
        facility_id: UUID,
        patient_id: UUID,
        encounter_id: UUID,
        language: Literal["hi", "en"],
    ) -> SummarySourceBundle:
        context = self._contexts.get((tenant_id, encounter_id))
        if context is None:
            raise SummaryNotFound("Confirmed encounter context not found")
        if context.facility_id != facility_id or context.patient_id != patient_id:
            raise SummaryNotFound("Confirmed encounter context not found")
        return SummarySourceBundle(
            **context.model_dump(
                include={
                    "tenant_id",
                    "facility_id",
                    "patient_id",
                    "encounter_id",
                    "chief_complaint",
                    "confirmed_answers",
                    "deterministic_red_flags",
                }
            ),
            language=language,
            reviewed_document_facts=[
                fact for _, fact in self._document_facts.get((tenant_id, encounter_id), [])
            ],
            reviewed_document_fact_ids=[
                fact_id for fact_id, _ in self._document_facts.get((tenant_id, encounter_id), [])
            ],
        )

    def set_reviewed_document_facts(
        self, tenant_id: UUID, encounter_id: UUID, facts: list[tuple[UUID, str]]
    ) -> None:
        self._document_facts[(tenant_id, encounter_id)] = facts[:100]


_GET_CONTEXT = """
SELECT * FROM confirmed_encounter_summary_context
WHERE tenant_id = $1 AND encounter_id = $2
"""

_INSERT_CONTEXT = """
INSERT INTO confirmed_encounter_summary_context (
    tenant_id, facility_id, patient_id, encounter_id, language,
    chief_complaint, confirmed_answers, deterministic_red_flags,
    confirmed_by_actor_id, confirmed_at, version
) VALUES ($1, $2, $3, $4, $5, $6, $7::JSONB, $8::JSONB, $9, $10, 1)
ON CONFLICT (tenant_id, encounter_id) DO NOTHING
RETURNING *
"""

_UPDATE_CONTEXT = """
UPDATE confirmed_encounter_summary_context SET
    facility_id = $3, patient_id = $4, language = $5, chief_complaint = $6,
    confirmed_answers = $7::JSONB, deterministic_red_flags = $8::JSONB,
    confirmed_by_actor_id = $9, confirmed_at = $10, version = version + 1
WHERE tenant_id = $1 AND encounter_id = $2 AND version = $11
  AND facility_id = $3 AND patient_id = $4
RETURNING *
"""

_GET_REVIEWED_FACTS = """
SELECT id, entity_type, normalized_value, unit
FROM reviewed_document_fact
WHERE tenant_id = $1 AND facility_id = $2 AND patient_id = $3
  AND encounter_id = $4 AND active
ORDER BY promoted_at, id
LIMIT 100
"""


class PostgresSummaryContextRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def confirm(
        self, *, tenant_id: UUID, actor_id: UUID, command: ConfirmEncounterContextCommand
    ) -> ConfirmedEncounterContext:
        flags = _deterministic_flags(command.chief_complaint, command.confirmed_answers)
        now = datetime.now(UTC)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await _set_tenant(connection, tenant_id)
                if command.expected_version is None:
                    row = await connection.fetchrow(
                        _INSERT_CONTEXT,
                        tenant_id,
                        command.facility_id,
                        command.patient_id,
                        command.encounter_id,
                        command.language,
                        command.chief_complaint,
                        json.dumps(command.confirmed_answers),
                        json.dumps(flags),
                        actor_id,
                        now,
                    )
                else:
                    row = await connection.fetchrow(
                        _UPDATE_CONTEXT,
                        tenant_id,
                        command.encounter_id,
                        command.facility_id,
                        command.patient_id,
                        command.language,
                        command.chief_complaint,
                        json.dumps(command.confirmed_answers),
                        json.dumps(flags),
                        actor_id,
                        now,
                        command.expected_version,
                    )
        if row is None:
            raise SummaryConflict("Confirmed context version is stale")
        return _context(row)

    async def assemble(
        self,
        *,
        tenant_id: UUID,
        facility_id: UUID,
        patient_id: UUID,
        encounter_id: UUID,
        language: Literal["hi", "en"],
    ) -> SummarySourceBundle:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await _set_tenant(connection, tenant_id)
                row = await connection.fetchrow(_GET_CONTEXT, tenant_id, encounter_id)
                if (
                    row is None
                    or row["facility_id"] != facility_id
                    or row["patient_id"] != patient_id
                ):
                    raise SummaryNotFound("Confirmed encounter context not found")
                fact_rows = await connection.fetch(
                    _GET_REVIEWED_FACTS, tenant_id, facility_id, patient_id, encounter_id
                )
        context = _context(row)
        facts = [
            f"{item['entity_type']}: {item['normalized_value']}"
            + (f" {item['unit']}" if item["unit"] else "")
            for item in fact_rows
        ]
        return SummarySourceBundle(
            tenant_id=tenant_id,
            facility_id=facility_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            language=language,
            chief_complaint=context.chief_complaint,
            confirmed_answers=context.confirmed_answers,
            deterministic_red_flags=context.deterministic_red_flags,
            reviewed_document_facts=facts,
            reviewed_document_fact_ids=[item["id"] for item in fact_rows],
        )


def _deterministic_flags(chief_complaint: str, answers: dict[str, Any]) -> list[str]:
    text = " ".join([chief_complaint, *(_safe_text(value) for value in answers.values())])
    return detect_red_flags(text)


def _safe_text(value: Any) -> str:
    return str(value)[:500]


async def _set_tenant(connection: Any, tenant_id: UUID) -> None:
    await connection.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))


def _context(row: Any) -> ConfirmedEncounterContext:
    values = dict(row)
    for key in ("confirmed_answers", "deterministic_red_flags"):
        if isinstance(values[key], str):
            values[key] = json.loads(values[key])
    return ConfirmedEncounterContext.model_validate(values)
