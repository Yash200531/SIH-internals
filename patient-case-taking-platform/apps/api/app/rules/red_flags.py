"""Prototype deterministic red-flag rules.

These rules are not clinically approved. They are enabled only on the demo
surface while their fixtures, ownership, and validation protocol are reviewed.
"""

from app.rules.engine import RuleResult, Severity, engine

RESPIRATORY_TERMS = (
    "difficulty breathing",
    "breathing difficulty",
    "cannot breathe",
    "shortness of breath",
    "breathless",
    "dyspnea",
    "सांस लेने में तकलीफ",
    "साँस लेने में तकलीफ",
    "सांस नहीं",
)

CHEST_PRESSURE_TERMS = (
    "chest pressure",
    "chest feels heavy",
    "सीना भारी",
    "छाती में दबाव",
)

LOSS_OF_CONSCIOUSNESS_TERMS = (
    "unconscious",
    "fainted",
    "loss of consciousness",
    "बेहोश",
    "बेहोशी",
)

STROKE_SIGN_TERMS = (
    "face drooping",
    "slurred speech",
    "one sided weakness",
    "बोलने में दिक्कत",
    "चेहरा टेढ़ा",
    "एक तरफ कमजोरी",
)

SEVERE_BLEEDING_TERMS = (
    "heavy bleeding",
    "bleeding won't stop",
    "बहुत खून",
    "खून नहीं रुक",
)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _is_explicitly_negated(text: str, term: str) -> bool:
    english_negations = (f"no {term}", f"not {term}", f"without {term}")
    hindi_negations = (f"{term} नहीं", f"{term} नही")
    return any(phrase in text for phrase in (*english_negations, *hindi_negations))


def _text_sources(answers: dict, context: dict) -> dict[str, str]:
    sources = {
        str(path): str(value)
        for path, value in context.get("text_sources", {}).items()
        if isinstance(value, str) and value.strip()
    }
    complaint = answers.get("chief_complaint")
    if isinstance(complaint, str) and complaint.strip():
        sources.setdefault("chief_complaint", complaint)
    for index, symptom in enumerate(answers.get("symptoms", [])):
        if isinstance(symptom, str) and symptom.strip():
            sources.setdefault(f"symptoms[{index}]", symptom)
    return sources


def _matching_paths(
    answers: dict, context: dict, terms: tuple[str, ...]
) -> tuple[str, ...]:
    matching: list[str] = []
    for path, source_text in _text_sources(answers, context).items():
        normalized = _normalize(source_text)
        if any(
            _normalize(term) in normalized
            and not _is_explicitly_negated(normalized, _normalize(term))
            for term in terms
        ):
            matching.append(path)
    return tuple(matching)


def _text_rule_result(
    *,
    answers: dict,
    context: dict,
    terms: tuple[str, ...],
    rule_id: str,
    rule_name: str,
    severity: Severity,
    message: str,
    explanation_code: str,
    rule_version: str = "1.0.0",
) -> RuleResult:
    evidence_paths = _matching_paths(answers, context, terms)
    return RuleResult(
        rule_id=rule_id,
        rule_version=rule_version,
        rule_name=rule_name,
        triggered=bool(evidence_paths),
        severity=severity,
        message=message if evidence_paths else "",
        requires_acknowledgement=severity in {Severity.HIGH, Severity.CRITICAL},
        explanation_code=explanation_code,
        owner_role="triage_nurse",
        evidence_paths=evidence_paths,
    )


@engine.register
def chest_pain_red_flag(answers: dict, context: dict) -> RuleResult:
    complaint = answers.get("chief_complaint", "").lower()
    symptoms = [s.lower() for s in answers.get("symptoms", [])]

    if "chest pain" in complaint or "chest pain" in symptoms:
        radiation = any(s in symptoms for s in ["arm pain", "jaw pain", "back pain", "left arm"])
        if radiation:
            return RuleResult(
                rule_id="RF-001",
                rule_name="Chest Pain with Radiation",
                triggered=True,
                severity=Severity.CRITICAL,
                message="Chest pain with radiation — immediate clinical review required",
                requires_acknowledgement=True,
                explanation_code="chest_pain_with_radiation",
                owner_role="triage_nurse",
                evidence_paths=("chief_complaint", "symptoms"),
            )
    return RuleResult(
        rule_id="RF-001",
        rule_name="Chest Pain with Radiation",
        triggered=False,
        severity=Severity.CRITICAL,
        message="",
    )


@engine.register
def difficulty_breathing_red_flag(answers: dict, context: dict) -> RuleResult:
    return _text_rule_result(
        answers=answers,
        context=context,
        terms=RESPIRATORY_TERMS,
        rule_id="RF-RESP-001",
        rule_version="1.0.1",
        rule_name="Reported Breathing Difficulty",
        severity=Severity.CRITICAL,
        message="Breathing difficulty reported — call clinical staff now",
        explanation_code="reported_breathing_difficulty",
    )


@engine.register
def chest_pressure_red_flag(answers: dict, context: dict) -> RuleResult:
    return _text_rule_result(
        answers=answers,
        context=context,
        terms=CHEST_PRESSURE_TERMS,
        rule_id="RF-CARDIAC-001",
        rule_name="Reported Chest Pressure",
        severity=Severity.CRITICAL,
        message="Chest pressure reported — call clinical staff now",
        explanation_code="reported_chest_pressure",
    )


@engine.register
def loss_of_consciousness_red_flag(answers: dict, context: dict) -> RuleResult:
    return _text_rule_result(
        answers=answers,
        context=context,
        terms=LOSS_OF_CONSCIOUSNESS_TERMS,
        rule_id="RF-CONSCIOUS-001",
        rule_name="Reported Loss of Consciousness",
        severity=Severity.CRITICAL,
        message="Loss of consciousness reported — call clinical staff now",
        explanation_code="reported_loss_of_consciousness",
    )


@engine.register
def stroke_signs_red_flag(answers: dict, context: dict) -> RuleResult:
    return _text_rule_result(
        answers=answers,
        context=context,
        terms=STROKE_SIGN_TERMS,
        rule_id="RF-NEURO-001",
        rule_name="Reported Neurological Warning Sign",
        severity=Severity.CRITICAL,
        message="A neurological warning sign was reported — call clinical staff now",
        explanation_code="reported_neurological_warning_sign",
    )


@engine.register
def severe_bleeding_red_flag(answers: dict, context: dict) -> RuleResult:
    return _text_rule_result(
        answers=answers,
        context=context,
        terms=SEVERE_BLEEDING_TERMS,
        rule_id="RF-BLEED-001",
        rule_name="Reported Severe Bleeding",
        severity=Severity.CRITICAL,
        message="Severe bleeding reported — call clinical staff now",
        explanation_code="reported_severe_bleeding",
    )


@engine.register
def fever_with_rash_red_flag(answers: dict, context: dict) -> RuleResult:
    symptoms = [s.lower() for s in answers.get("symptoms", [])]
    fever = "fever" in symptoms or "fever" in answers.get("chief_complaint", "").lower()
    rash = "rash" in symptoms

    if fever and rash:
        return RuleResult(
            rule_id="RF-003",
            rule_name="Fever with Rash",
            triggered=True,
            severity=Severity.MEDIUM,
            message="Fever with rash — clinical evaluation recommended",
            requires_acknowledgement=False,
            explanation_code="reported_fever_with_rash",
            owner_role="triage_nurse",
            evidence_paths=("symptoms",),
        )
    return RuleResult(
        rule_id="RF-003",
        rule_name="Fever with Rash",
        triggered=False,
        severity=Severity.MEDIUM,
        message="",
    )
