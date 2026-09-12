"""Shared HTTP/voice authentication with explicit provider and internal grants."""

from functools import lru_cache
from typing import Literal

import asyncpg
import jwt
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.auth.identity_repository import IdentityRepository
from app.auth.jwt_verifier import (
    ClerkSessionVerifier,
    CredentialRejected,
    IdentityProviderUnavailable,
)
from app.auth.token import TokenPayload, validate_token
from app.config import settings
from app.database import get_postgres_pool


class ApplicationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=1, max_length=255)
    audience: str = Field(min_length=1, max_length=128)
    authorized_parties: frozenset[str] = Field(min_length=1, max_length=10)
    allowed_roles: frozenset[Literal["patient", "doctor", "nurse", "admin", "receptionist", "kiosk_operator", "caregiver"]] = Field(min_length=1)


@lru_cache(maxsize=1)
def configured_boundaries(configuration: str):
    boundaries = TypeAdapter(list[ApplicationBoundary]).validate_json(configuration)
    if not 1 <= len(boundaries) <= 5:
        raise ValueError("One to five identity applications must be configured")
    result = {}
    for boundary in boundaries:
        key = (boundary.issuer, boundary.audience)
        if key in result:
            raise ValueError("Duplicate identity application boundary")
        result[key] = (boundary, ClerkSessionVerifier(
            issuer=boundary.issuer, audience=boundary.audience,
            authorized_parties=boundary.authorized_parties,
        ))
    return result


async def get_identity_repository() -> IdentityRepository:
    return IdentityRepository(await get_postgres_pool())


async def authenticate_token(token: str) -> TokenPayload:
    if not token or len(token) > 16384:
        raise HTTPException(401, "Invalid session credential")
    if settings.AUTH_PROVIDER == "demo":
        if settings.APP_ENV not in {"development", "test"}:
            raise HTTPException(503, "Demo authentication is disabled")
        payload = validate_token(token)
        if payload is None:
            raise HTTPException(401, "Invalid or expired token")
        return payload
    try:
        boundaries = configured_boundaries(settings.CLERK_APPLICATIONS_JSON)
    except ValueError as exc:
        raise HTTPException(503, "Identity provider is not configured") from exc
    try:
        # Unverified claims select only among configured boundaries. They grant no
        # identity or scope, and the selected verifier checks their signed values.
        unverified = jwt.decode(token, options={"verify_signature": False})
        issuer, audience = unverified.get("iss"), unverified.get("aud")
        if not isinstance(issuer, str) or not isinstance(audience, str) or (issuer, audience) not in boundaries:
            raise CredentialRejected("Application boundary rejected")
        boundary, verifier = boundaries[(issuer, audience)]
        session = await verifier.verify(token)
        repository = await get_identity_repository()
        identity = await repository.resolve(session, token)
    except (CredentialRejected, jwt.PyJWTError) as exc:
        raise HTTPException(401, "Invalid or expired session") from exc
    except (IdentityProviderUnavailable, asyncpg.PostgresError, OSError, TimeoutError) as exc:
        raise HTTPException(503, "Identity verification is temporarily unavailable") from exc
    if identity is None or identity.role not in boundary.allowed_roles:
        raise HTTPException(403, "Active internal identity grant required for this application")
    return identity
