"""Clerk authentication adapter.
Validates JWT tokens, maps Clerk IDs to internal identities.
Replaceable at the adapter boundary for hospital SSO."""
import time
from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass
class AuthenticatedUser:
    internal_id: UUID
    clerk_user_id: str
    email: str | None
    role: str  # doctor, nurse, receptionist, admin, kiosk_operator
    tenant_id: UUID
    facility_ids: list[UUID]
    is_active: bool


# In-memory user store (replace with DB in production)
_users: dict[str, dict] = {}


def register_user(clerk_user_id: str, email: str, role: str, tenant_id: UUID, facility_ids: list[UUID]) -> dict:
    """Register a new user from Clerk webhook or manual creation."""
    internal_id = uuid4()
    user = {
        "internal_id": internal_id,
        "clerk_user_id": clerk_user_id,
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
        "facility_ids": facility_ids,
        "is_active": True,
        "created_at": time.time(),
    }
    _users[clerk_user_id] = user
    return user


def get_user_by_clerk_id(clerk_user_id: str) -> dict | None:
    """Look up internal user by Clerk ID."""
    return _users.get(clerk_user_id)


def get_user_by_internal_id(internal_id: UUID) -> dict | None:
    """Look up internal user by internal UUID."""
    for user in _users.values():
        if user["internal_id"] == internal_id:
            return user
    return None


def deactivate_user(clerk_user_id: str) -> bool:
    """Deactivate a user account."""
    user = _users.get(clerk_user_id)
    if user:
        user["is_active"] = False
        return True
    return False
