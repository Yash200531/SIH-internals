"""Centralized audit event emitter.
All sensitive operations must call emit() to produce an immutable audit record."""
import time
from uuid import UUID, uuid4


def safe_uuid(value: str | None) -> UUID | None:
    """Convert a string to UUID, returning None if invalid."""
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


class AuditEmitter:
    """In-memory audit emitter. Replace with append-only DB/Kafka in production."""

    def __init__(self):
        self._events: list[dict] = []

    def emit(
        self,
        *,
        tenant_id: UUID,
        actor_id: UUID | None,
        actor_type: str,  # "staff", "patient", "system", "kiosk"
        actor_role: str | None,
        action: str,  # "create", "read", "update", "delete", "grant_consent", "revoke_consent", "session_create", "session_expire", "session_wipe", "break_glass", "status_change", "abha_link"
        resource_type: str,  # "patient", "encounter", "consent", "session", "clinical_summary", "audit"
        resource_id: UUID | None,
        purpose: str | None = None,
        outcome: str = "success",  # "success", "failure", "denied"
        outcome_detail: str | None = None,
        facility_id: UUID | None = None,
        audit_metadata: dict | None = None,
    ) -> dict:
        """Emit an immutable audit event. Returns the event dict."""
        event = {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "actor_role": actor_role,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "purpose": purpose,
            "outcome": outcome,
            "outcome_detail": outcome_detail,
            "facility_id": facility_id,
            "metadata": audit_metadata or {},
            "created_at": time.time(),
        }
        self._events.append(event)
        return event

    def query(
        self,
        tenant_id: UUID,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        actor_id: UUID | None = None,
        action: str | None = None,
    ) -> list[dict]:
        """Query audit events with filters."""
        results = []
        for e in self._events:
            if e["tenant_id"] != tenant_id:
                continue
            if resource_type and e["resource_type"] != resource_type:
                continue
            if resource_id and e["resource_id"] != resource_id:
                continue
            if actor_id and e["actor_id"] != actor_id:
                continue
            if action and e["action"] != action:
                continue
            results.append(e)
        return results


# Singleton
audit_emitter = AuditEmitter()
