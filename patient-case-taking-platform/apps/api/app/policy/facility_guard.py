"""FastAPI dependency that enforces facility-level data isolation.
Every request carrying a resource must match the caller's facility."""
from fastapi import Depends, HTTPException

from app.auth.dependencies import get_current_user
from app.auth.token import TokenPayload
from app.policy.engine import policy_engine


def require_facility_access(resource_facility_id: str):
    """Return a dependency that checks the caller can access resources at the given facility."""
    async def _check(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        # Admin with tenant_match can跨 facility within tenant
        if user.role == "admin":
            return user

        # Check if user's facility list includes the resource facility
        if resource_facility_id not in user.facility_ids:
            # Also check via policy engine
            allowed = policy_engine.evaluate(
                user.role, "read", "patient",
                {
                    "user_facility_id": user.facility_ids[0] if user.facility_ids else None,
                    "resource_facility_id": resource_facility_id,
                    "user_tenant_id": user.tenant_id,
                    "resource_tenant_id": user.tenant_id,
                }
            )
            if not allowed:
                raise HTTPException(
                    status_code=403,
                    detail="Facility isolation: you cannot access resources at this facility"
                )
        return user
    return _check
