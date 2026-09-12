"""Canonical Phase 6 deterministic triage evaluation boundary."""

from dataclasses import dataclass
from typing import Literal

import app.rules.red_flags  # noqa: F401  # register the canonical rule set
from app.rules.engine import RuleResult, Severity, engine

NO_CONFIGURED_FLAG: Literal["no_configured_flag"] = "no_configured_flag"
FLAGS_TRIGGERED: Literal["flags_triggered"] = "flags_triggered"
TriageOutcome = Literal["no_configured_flag", "flags_triggered"]


@dataclass(frozen=True)
class TriageEvaluation:
    outcome: TriageOutcome
    ruleset_version: str
    flags: tuple[RuleResult, ...]


def evaluate_text_sources(text_sources: dict[str, str]) -> TriageEvaluation:
    """Evaluate bounded text sources without copying source values into results."""
    bounded_sources = {
        str(path)[:160]: str(value)[:2_000]
        for path, value in text_sources.items()
        if str(value).strip()
    }
    triggered = engine.evaluate({}, {"text_sources": bounded_sources})
    red_flags = tuple(
        sorted(
            (result for result in triggered if result.rule_id.startswith("RF-")),
            key=lambda result: (-_severity_rank(result.severity), result.rule_id),
        )
    )
    return TriageEvaluation(
        outcome=FLAGS_TRIGGERED if red_flags else NO_CONFIGURED_FLAG,
        ruleset_version=engine.version,
        flags=red_flags,
    )


def detect_red_flags(text: str) -> list[str]:
    """Compatibility adapter returning canonical stable rule identifiers."""
    return [flag.rule_id for flag in evaluate_text_sources({"text": text}).flags]


def _severity_rank(severity: Severity) -> int:
    return {
        Severity.LOW: 1,
        Severity.MEDIUM: 2,
        Severity.HIGH: 3,
        Severity.CRITICAL: 4,
    }[severity]
