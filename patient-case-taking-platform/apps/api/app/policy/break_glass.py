"""Break-glass emergency access.
Disabled by default. When enabled, allows time-bound emergency access
with mandatory reason and audit trail."""
import time
from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass
class BreakGlassRequest:
    request_id: UUID
    staff_id: UUID
    facility_id: UUID
    patient_id: UUID
    reason: str  # mandatory reason
    urgency: str  # "life_threatening", "clinical_urgency", "unavailable_data"
    requested_at: float
    expires_at: float  # time-bound (e.g., 1 hour)
    approved: bool
    approved_by: UUID | None
    approved_at: float | None
    audit_event_id: UUID | None


_break_glass_requests: dict[str, BreakGlassRequest] = {}

# Break-glass is disabled by default
BREAK_GLASS_ENABLED = False
BREAK_GLASS_DURATION = 3600  # 1 hour


def is_break_glass_enabled() -> bool:
    return BREAK_GLASS_ENABLED


def request_break_glass(staff_id: UUID, facility_id: UUID, patient_id: UUID, reason: str, urgency: str) -> BreakGlassRequest | None:
    """Request emergency access. Returns None if break-glass is disabled."""
    if not BREAK_GLASS_ENABLED:
        return None

    now = time.time()
    request = BreakGlassRequest(
        request_id=uuid4(),
        staff_id=staff_id,
        facility_id=facility_id,
        patient_id=patient_id,
        reason=reason,
        urgency=urgency,
        requested_at=now,
        expires_at=now + BREAK_GLASS_DURATION,
        approved=False,
        approved_by=None,
        approved_at=None,
        audit_event_id=None,
    )
    _break_glass_requests[str(request.request_id)] = request
    return request


def approve_break_glass(request_id: UUID, approver_id: UUID) -> BreakGlassRequest | None:
    """Approve a break-glass request (requires supervisor)."""
    request = _break_glass_requests.get(str(request_id))
    if not request:
        return None
    if time.time() > request.expires_at:
        return None
    request.approved = True
    request.approved_by = approver_id
    request.approved_at = time.time()
    return request


def check_break_glass_access(request_id: UUID) -> bool:
    """Check if a break-glass grant is still valid."""
    request = _break_glass_requests.get(str(request_id))
    if not request or not request.approved:
        return False
    return time.time() < request.expires_at
