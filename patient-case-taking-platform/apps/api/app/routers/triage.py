"""Demo-gated Phase 6 deterministic triage contract."""

from fastapi import APIRouter

from app.audit.emitter import audit_emitter
from app.rules.schemas import (
    TriageEvaluationRequest,
    TriageEvaluationResponse,
    TriageFlagResponse,
)
from app.rules.triage import evaluate_text_sources

router = APIRouter(prefix="/api/v1/triage", tags=["triage"])


@router.post("/evaluate", response_model=TriageEvaluationResponse)
async def evaluate_triage(body: TriageEvaluationRequest) -> TriageEvaluationResponse:
    sources = {
        "chief_complaint": body.chief_complaint,
        **{
            f"confirmed_answers.{key}": value
            for key, value in body.confirmed_answers.items()
        },
    }
    evaluation = evaluate_text_sources(sources)
    flags = [
        TriageFlagResponse(
            rule_id=flag.rule_id,
            rule_version=flag.rule_version,
            ruleset_version=flag.ruleset_version,
            severity=flag.severity,
            explanation_code=flag.explanation_code,
            message=flag.message,
            owner_role=flag.owner_role,
            requires_acknowledgement=flag.requires_acknowledgement,
            evidence_paths=list(flag.evidence_paths),
            approval_status="prototype_only",
        )
        for flag in evaluation.flags
    ]
    audit_emitter.emit(
        tenant_id=body.tenant_id,
        actor_id=None,
        actor_type="system",
        actor_role="triage_evaluator",
        action="triage_evaluate",
        resource_type="encounter",
        resource_id=body.encounter_id,
        purpose="deterministic_safety_screening",
        facility_id=body.facility_id,
        audit_metadata={
            "ruleset_version": evaluation.ruleset_version,
            "input_version": body.input_version,
            "outcome": evaluation.outcome,
            "rule_ids": [flag.rule_id for flag in evaluation.flags],
            "durable_alert_created": False,
        },
    )
    return TriageEvaluationResponse(
        outcome=evaluation.outcome,
        ruleset_version=evaluation.ruleset_version,
        flags=flags,
    )
