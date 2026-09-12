"""Demo token storage and shared internal authorization payload.
External verification and mapping live in the authentication service."""
import hashlib
import secrets
import time
from dataclasses import dataclass


@dataclass
class TokenPayload:
    user_id: str
    email: str | None
    role: str
    tenant_id: str
    facility_ids: list[str]
    issued_at: float
    expires_at: float
    token_hash: str
    mfa_verified: bool = False  # MFA-ready: False until MFA challenge completed
    session_id: str | None = None  # links to session for rotation tracking
    external_issuer: str | None = None
    external_audience: str | None = None
    external_subject: str | None = None


# Dev token store
_tokens: dict[str, TokenPayload] = {}


def create_dev_token(user_id: str, email: str | None, role: str, tenant_id: str, facility_ids: list[str], ttl_seconds: int = 3600, mfa_verified: bool = False, session_id: str | None = None) -> str:
    """Create a dev-only token. In production, Clerk issues tokens."""
    now = time.time()
    for expired_hash, existing in list(_tokens.items()):
        if existing.expires_at <= now:
            _tokens.pop(expired_hash, None)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    payload = TokenPayload(
        user_id=user_id,
        email=email,
        role=role,
        tenant_id=tenant_id,
        facility_ids=facility_ids,
        issued_at=time.time(),
        expires_at=time.time() + ttl_seconds,
        token_hash=token_hash,
        mfa_verified=mfa_verified,
        session_id=session_id,
    )
    _tokens[token_hash] = payload
    return token


def validate_token(token: str) -> TokenPayload | None:
    """Validate token and return payload. Returns None if invalid/expired."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    payload = _tokens.get(token_hash)
    if not payload:
        return None
    if time.time() >= payload.expires_at:
        del _tokens[token_hash]
        return None
    return payload


def revoke_token(token: str) -> bool:
    """Revoke a token."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    if token_hash in _tokens:
        del _tokens[token_hash]
        return True
    return False


def rotate_token(old_token: str, new_role: str | None = None) -> str | None:
    """Rotate token on privilege elevation. Returns new token or None if old is invalid."""
    old_payload = validate_token(old_token)
    if not old_payload:
        return None
    revoke_token(old_token)
    new_token = create_dev_token(
        old_payload.user_id, old_payload.email,
        new_role or old_payload.role,
        old_payload.tenant_id, old_payload.facility_ids,
        mfa_verified=old_payload.mfa_verified,
        session_id=old_payload.session_id,
    )
    return new_token
