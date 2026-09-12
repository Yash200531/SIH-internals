"""RBAC + ABAC policy engine.
Combines role-based access control with attribute-based conditions."""
from dataclasses import dataclass, field
from enum import Enum


class Effect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass
class PolicyRule:
    rule_id: str
    role: str  # "*" for any role
    action: str  # "*" for any action
    resource: str  # "*" for any resource
    effect: Effect
    conditions: dict = field(default_factory=dict)


class PolicyEngine:
    """Evaluate access requests against RBAC + ABAC rules."""

    def __init__(self):
        self._rules: list[PolicyRule] = []

    def add_rule(self, rule: PolicyRule):
        self._rules.append(rule)

    def evaluate(
        self,
        role: str,
        action: str,
        resource: str,
        context: dict | None = None,
    ) -> bool:
        """Evaluate if access is allowed. Default deny."""
        ctx = context or {}

        for rule in self._rules:
            if rule.role != "*" and rule.role != role:
                continue
            if rule.action != "*" and rule.action != action:
                continue
            if rule.resource != "*" and rule.resource != resource:
                continue

            # Check ABAC conditions
            if not self._check_conditions(rule.conditions, ctx):
                continue

            return rule.effect == Effect.ALLOW

        return False  # default deny

    def _check_conditions(self, conditions: dict, context: dict) -> bool:
        """Check ABAC conditions against request context."""
        if not conditions:
            return True

        for key, expected in conditions.items():
            if key == "facility_match":
                if expected and context.get("user_facility_id") != context.get("resource_facility_id"):
                    return False
            elif key == "tenant_match":
                if expected and context.get("user_tenant_id") != context.get("resource_tenant_id"):
                    return False
            elif key == "purpose":
                if context.get("purpose") != expected:
                    return False
            elif key == "emergency_only":
                if expected and not context.get("is_emergency"):
                    return False

        return True


# Singleton
policy_engine = PolicyEngine()


# Default rules
def load_default_rules():
    """Load default RBAC + ABAC rules."""
    policy_engine.add_rule(PolicyRule(
        rule_id="R001", role="admin", action="*", resource="*",
        effect=Effect.ALLOW, conditions={"tenant_match": True}
    ))
    policy_engine.add_rule(PolicyRule(
        rule_id="R002", role="doctor", action="read", resource="patient",
        effect=Effect.ALLOW, conditions={"facility_match": True}
    ))
    policy_engine.add_rule(PolicyRule(
        rule_id="R003", role="doctor", action="write", resource="encounter",
        effect=Effect.ALLOW, conditions={"facility_match": True}
    ))
    policy_engine.add_rule(PolicyRule(
        rule_id="R004", role="doctor", action="sign", resource="clinical_summary",
        effect=Effect.ALLOW, conditions={"facility_match": True}
    ))
    policy_engine.add_rule(PolicyRule(
        rule_id="R005", role="nurse", action="read", resource="patient",
        effect=Effect.ALLOW, conditions={"facility_match": True}
    ))
    policy_engine.add_rule(PolicyRule(
        rule_id="R006", role="nurse", action="write", resource="encounter",
        effect=Effect.ALLOW, conditions={"facility_match": True}
    ))
    policy_engine.add_rule(PolicyRule(
        rule_id="R007", role="receptionist", action="read", resource="patient",
        effect=Effect.ALLOW, conditions={"facility_match": True}
    ))
    policy_engine.add_rule(PolicyRule(
        rule_id="R008", role="receptionist", action="write", resource="patient",
        effect=Effect.ALLOW, conditions={"facility_match": True}
    ))
    policy_engine.add_rule(PolicyRule(
        rule_id="R009", role="kiosk_operator", action="read", resource="patient",
        effect=Effect.ALLOW, conditions={"facility_match": True}
    ))
    policy_engine.add_rule(PolicyRule(
        rule_id="R010", role="*", action="break_glass", resource="*",
        effect=Effect.DENY, conditions={"emergency_only": True}  # break-glass is special
    ))
    # Break-glass allows access but requires acknowledgement
    policy_engine.add_rule(PolicyRule(
        rule_id="R011", role="doctor", action="break_glass", resource="*",
        effect=Effect.ALLOW, conditions={"emergency_only": True}
    ))

load_default_rules()
