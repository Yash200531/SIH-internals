import app.rules.clinical_safety  # noqa: F401

# importing modules triggers registration
import app.rules.red_flags  # noqa: F401
from app.rules.engine import Severity, engine


def test_chest_pain_red_flag():
    results = engine.evaluate({"chief_complaint": "chest pain", "symptoms": ["arm pain"]})
    assert len(results) == 1
    assert results[0].rule_id == "RF-001"
    assert results[0].severity == Severity.CRITICAL
    assert results[0].requires_acknowledgement is True


def test_chest_pain_no_radiation():
    results = engine.evaluate({"chief_complaint": "chest pain", "symptoms": []})
    assert len(results) == 0


def test_difficulty_breathing_red_flag():
    results = engine.evaluate({"chief_complaint": "shortness of breath", "symptoms": []})
    assert len(results) == 1
    assert results[0].rule_id == "RF-RESP-001"
    assert results[0].severity == Severity.CRITICAL
    assert results[0].ruleset_version == "phase6.prototype.v2"


def test_fever_with_rash_red_flag():
    results = engine.evaluate({"chief_complaint": "", "symptoms": ["fever", "rash"]})
    assert len(results) == 1
    assert results[0].rule_id == "RF-003"
    assert results[0].severity == Severity.MEDIUM


def test_medication_allergy_check():
    results = engine.evaluate({
        "allergies": ["penicillin"],
        "current_medications": ["cephalexin (cephalosporin)"],
    })
    assert len(results) == 1
    assert results[0].rule_id == "CS-001"
    assert results[0].severity == Severity.CRITICAL


def test_no_allergy_conflict():
    results = engine.evaluate({
        "allergies": ["sulfa"],
        "current_medications": ["amoxicillin"],
    })
    assert len(results) == 0
