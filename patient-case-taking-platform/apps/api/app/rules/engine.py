"""Deterministic rules engine skeleton.
Rules are clinician-owned, testable, and versioned.
No LLM is the sole red-flag detector."""
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    rule_name: str
    triggered: bool
    severity: Severity
    message: str
    requires_acknowledgement: bool = False
    rule_version: str = "1.0.0"
    ruleset_version: str = ""
    explanation_code: str = ""
    owner_role: str = "clinician"
    evidence_paths: tuple[str, ...] = ()
    approval_status: str = "prototype_only"


Rule = Callable[[dict, dict], RuleResult]


class RulesEngine:
    def __init__(self, version: str = "phase6.prototype.v2"):
        self.version = version
        self._rules: list[Rule] = []

    def register(self, rule_func: Rule) -> Rule:
        self._rules.append(rule_func)
        return rule_func

    def evaluate(self, answers: dict, context: dict | None = None) -> list[RuleResult]:
        results: list[RuleResult] = []
        for rule in self._rules:
            result = rule(answers, context or {})
            if result.triggered:
                results.append(replace(result, ruleset_version=self.version))
        return results


engine = RulesEngine()
