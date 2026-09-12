"""Versioned request and response contracts for demo triage evaluation."""

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.rules.engine import Severity


class TriageEvaluationRequest(BaseModel):
    tenant_id: UUID
    facility_id: UUID
    encounter_id: UUID
    input_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)
    language: Literal["hi", "en"] = "en"
    chief_complaint: str = Field(default="", max_length=500)
    confirmed_answers: dict[str, str] = Field(default_factory=dict)

    @field_validator("confirmed_answers")
    @classmethod
    def bound_confirmed_answers(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 100:
            raise ValueError("confirmed_answers cannot contain more than 100 fields")
        if any(
            re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key) is None
            for key in value
        ):
            raise ValueError("confirmed answer keys must be controlled ontology identifiers")
        if any(len(answer) > 2_000 for answer in value.values()):
            raise ValueError("confirmed answer key or value exceeds the allowed length")
        return value


class TriageFlagResponse(BaseModel):
    rule_id: str
    rule_version: str
    ruleset_version: str
    severity: Severity
    explanation_code: str
    message: str
    owner_role: str
    requires_acknowledgement: bool
    evidence_paths: list[str]
    approval_status: Literal["prototype_only"] = "prototype_only"


class TriageEvaluationResponse(BaseModel):
    outcome: Literal["no_configured_flag", "flags_triggered"]
    ruleset_version: str
    flags: list[TriageFlagResponse]
    no_match_is_not_safe_or_routine: Literal[True] = True
    durable_alert_created: Literal[False] = False
    schema_version: Literal["phase6.triage-evaluation.v1"] = "phase6.triage-evaluation.v1"
