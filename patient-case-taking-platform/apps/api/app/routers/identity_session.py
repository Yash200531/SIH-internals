"""Current internal identity and platform session revocation for both providers."""

from fastapi import APIRouter, Depends, Header, Response

from app.auth.dependencies import get_current_user
from app.auth.service import get_identity_repository
from app.auth.token import TokenPayload, revoke_token

router = APIRouter(prefix="/api/v1/auth", tags=["identity"])


@router.get("/me")
async def me(response: Response, user: TokenPayload = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "user_id": user.user_id, "tenant_id": user.tenant_id, "role": user.role,
        "facility_ids": user.facility_ids, "expires_at": user.expires_at,
        "provider": "clerk" if user.external_issuer else "demo",
    }


@router.post("/session/revoke")
async def revoke_session(
    response: Response, user: TokenPayload = Depends(get_current_user),
    authorization: str = Header(...),
):
    if user.external_issuer:
        await (await get_identity_repository()).revoke_session(user)
    else:
        revoke_token(authorization.partition(" ")[2].strip())
    response.headers["Cache-Control"] = "private, no-store"
    return {"status": "revoked", "scope": "platform_session"}
