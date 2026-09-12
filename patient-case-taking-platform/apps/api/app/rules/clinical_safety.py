"""Clinical safety rules — medication, allergy, and negation checks."""
from app.rules.engine import RuleResult, Severity, engine


@engine.register
def medication_allergy_check(answers: dict, context: dict) -> RuleResult:
    allergies = [a.lower() for a in answers.get("allergies", [])]
    medications = [m.lower() for m in answers.get("current_medications", [])]

    if "penicillin" in allergies and any("cephalosporin" in m for m in medications):
        return RuleResult(
            rule_id="CS-001",
            rule_name="Medication-Allergy Cross-Reactivity",
            triggered=True,
            severity=Severity.CRITICAL,
            message="Patient allergic to penicillin — cephalosporin prescribed. Cross-reactivity risk.",
            requires_acknowledgement=True,
        )
    return RuleResult(
        rule_id="CS-001",
        rule_name="Medication-Allergy Cross-Reactivity",
        triggered=False,
        severity=Severity.CRITICAL,
        message="",
    )
