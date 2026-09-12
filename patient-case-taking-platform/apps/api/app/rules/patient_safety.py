"""Atomic patient-confirmed safety evaluation, without an LLM dependency."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.patient_portal.service import PatientIdentity
from app.rules.alert_lifecycle import AlertActor
from app.rules.alert_repository import AlertEvidence, PostgresAlertRepository
from app.rules.schemas import TriageEvaluationRequest
from app.rules.triage import evaluate_text_sources


class PatientSafetyConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facility_id: UUID
    encounter_id: UUID
    consent_id: UUID
    input_version: int = Field(ge=1)
    confirmed: Literal[True]
    chief_complaint: str = Field(max_length=500)
    confirmed_answers: dict[str, str] = Field(default_factory=dict)

    @field_validator("confirmed_answers")
    @classmethod
    def bound_answers(cls, value):
        return TriageEvaluationRequest.bound_confirmed_answers(value)


class PatientSafetyService:
    def __init__(self, pool: Any):
        self.pool = pool

    async def confirm(self, identity: PatientIdentity, command: PatientSafetyConfirmation) -> dict:
        if command.facility_id not in identity.facility_ids:
            raise HTTPException(403, "Patient facility access denied")
        sources = {
            "chief_complaint": command.chief_complaint,
            **{
                f"confirmed_answers.{key}": value
                for key, value in command.confirmed_answers.items()
            },
        }
        evaluation = evaluate_text_sources(sources)
        evidence = {
            "patient_id": str(identity.patient_id),
            "consent_id": str(command.consent_id),
            "confirmed_sources": sources,
            "input_version": command.input_version,
            "source_type": "patient_confirmed",
        }
        fingerprint = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        actor = AlertActor(
            actor_id=identity.patient_id,
            tenant_id=identity.tenant_id,
            facility_ids=frozenset(identity.facility_ids),
            role="patient",
        )
        repository = PostgresAlertRepository(self.pool)
        flags = []
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await repository._tenant(connection, identity.tenant_id)
                consent = await connection.fetchrow(
                    "SELECT patient_id,encounter_id,status,purpose,expires_at FROM consent_artifact "
                    "WHERE tenant_id=$1 AND id=$2 FOR SHARE",
                    identity.tenant_id,
                    command.consent_id,
                )
                if (
                    consent is None
                    or consent["patient_id"] != identity.patient_id
                    or consent["encounter_id"] != command.encounter_id
                    or consent["status"] != "granted"
                    or consent["purpose"] != "treatment"
                    or (
                        consent["expires_at"] is not None
                        and consent["expires_at"] <= datetime.now(UTC)
                    )
                ):
                    raise HTTPException(403, "Active matching treatment consent required")
                for rule in evaluation.flags:
                    flags.append(
                        await repository.raise_flag(
                            actor=actor,
                            facility_id=command.facility_id,
                            encounter_id=command.encounter_id,
                            evidence=AlertEvidence(
                                input_version=command.input_version, fingerprint=fingerprint
                            ),
                            rule=rule,
                            protected_evidence=evidence,
                            connection=connection,
                        )
                    )
        return {
            "outcome": evaluation.outcome,
            "interrupt_required": bool(flags),
            "durable_alert_count": len(flags),
            "staff_acknowledged": False,
            "approval_status": "prototype_only",
            "no_match_is_not_safe_or_routine": True,
        }
