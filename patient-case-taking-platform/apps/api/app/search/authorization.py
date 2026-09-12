"""Token-derived authorization scope for Phase 9 clinical retrieval."""

from dataclasses import dataclass
from uuid import UUID

from app.auth.token import TokenPayload


class SearchAuthorizationDenied(PermissionError):
    pass


@dataclass(frozen=True)
class SearchIdentity:
    tenant_id: UUID
    patient_id: UUID
    actor_id: UUID
    actor_role: str
    facility_ids: frozenset[UUID]
    purpose: str = "treatment"


def authorize_search_identity(
    user: TokenPayload,
    *,
    requested_patient_id: UUID | None,
    requested_facility_ids: set[UUID] | None = None,
) -> SearchIdentity:
    if user.role not in {"patient", "doctor", "nurse"}:
        raise SearchAuthorizationDenied("Clinical search role required")
    try:
        tenant_id = UUID(user.tenant_id)
        actor_id = UUID(user.user_id)
        token_facilities = {UUID(value) for value in user.facility_ids}
    except (TypeError, ValueError) as exc:
        raise SearchAuthorizationDenied("Invalid authorization scope") from exc
    if not token_facilities:
        raise SearchAuthorizationDenied("Facility scope required")

    if user.role == "patient":
        patient_id = actor_id
    elif requested_patient_id is None:
        raise SearchAuthorizationDenied("Patient scope is required")
    else:
        patient_id = requested_patient_id

    facilities = requested_facility_ids or token_facilities
    if not facilities or not facilities.issubset(token_facilities):
        raise SearchAuthorizationDenied("Facility access denied")
    return SearchIdentity(
        tenant_id=tenant_id,
        patient_id=patient_id,
        actor_id=actor_id,
        actor_role=user.role,
        facility_ids=frozenset(facilities),
    )
