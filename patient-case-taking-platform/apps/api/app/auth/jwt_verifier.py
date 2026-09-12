"""Verify a configured Clerk session boundary; claims never grant clinical roles."""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
import jwt


class CredentialRejected(ValueError):
    pass


class IdentityProviderUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifiedSession:
    issuer: str
    audience: str
    subject: str
    session_id: str
    authorized_party: str
    issued_at: int
    expires_at: int


class ClerkSessionVerifier:
    def __init__(
        self, *, issuer: str, audience: str, authorized_parties: frozenset[str],
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        parsed = urlsplit(issuer)
        if (
            parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or issuer.endswith("/")
            or not audience.strip() or not authorized_parties
        ):
            raise ValueError("Pinned HTTPS issuer, audience and authorized origins are required")
        self.issuer = issuer
        self.audience = audience
        self.authorized_parties = authorized_parties
        self.transport = transport
        self.clock = clock
        self._keys: dict[str, Any] = {}
        self._expires_at = 0.0
        self._last_refresh = float("-inf")
        self._lock = asyncio.Lock()

    async def _key(self, kid: str):
        async with self._lock:
            now = self.clock()
            if now < self._expires_at and kid in self._keys:
                return self._keys[kid]
            # Bound forced refreshes from attacker-controlled unknown key IDs.
            if now - self._last_refresh < 5:
                raise CredentialRejected("Signing key is unavailable")
            self._last_refresh = now
            try:
                async with httpx.AsyncClient(transport=self.transport, timeout=5, follow_redirects=False) as client:
                    async with client.stream("GET", f"{self.issuer}/.well-known/jwks.json") as response:
                        response.raise_for_status()
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 65536:
                                raise ValueError("JWKS exceeds size limit")
                document = json.loads(body)
                items = document["keys"]
                if not isinstance(items, list) or not 1 <= len(items) <= 10:
                    raise ValueError("Invalid signing key set")
                keys = {}
                seen = set()
                for item in items:
                    key_id = item.get("kid")
                    if not isinstance(key_id, str) or not 1 <= len(key_id) <= 128 or key_id in seen or "d" in item:
                        raise ValueError("Missing or ambiguous key ID")
                    seen.add(key_id)
                    if item.get("kty") != "RSA" or item.get("alg", "RS256") != "RS256" or item.get("use", "sig") != "sig":
                        continue
                    if "key_ops" in item and "verify" not in item["key_ops"]:
                        continue
                    key = jwt.PyJWK.from_dict(item, algorithm="RS256").key
                    if not 2048 <= key.key_size <= 8192:
                        raise ValueError("Invalid signing key size")
                    keys[key_id] = key
                if not keys:
                    raise ValueError("No supported signing keys")
                self._keys = keys
                self._expires_at = self.clock() + 60
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, jwt.PyJWTError) as exc:
                raise IdentityProviderUnavailable("Signing keys could not be verified") from exc
            if kid not in self._keys:
                raise CredentialRejected("Unknown signing key")
            return self._keys[kid]

    async def verify(self, token: str) -> VerifiedSession:
        if not token or len(token) > 16384:
            raise CredentialRejected("Invalid session credential")
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if (
                header.get("alg") != "RS256" or header.get("typ", "JWT") != "JWT"
                or "crit" in header or not isinstance(kid, str) or not 1 <= len(kid) <= 128
            ):
                raise CredentialRejected("Unsupported session credential")
            key = await self._key(kid)
            claims = jwt.decode(
                token, key, algorithms=["RS256"], issuer=self.issuer, audience=self.audience,
                leeway=5,
                options={"require": ["iss", "aud", "sub", "sid", "azp", "iat", "nbf", "exp"], "strict_aud": True},
            )
            if (
                claims["azp"] not in self.authorized_parties
                or claims.get("sts") not in (None, "active") or claims.get("act") is not None
                or any(type(claims[field]) is not int for field in ("iat", "nbf", "exp"))
                or claims["exp"] <= claims["iat"]
                or any(not isinstance(claims[field], str) or not 1 <= len(claims[field]) <= 128 for field in ("sub", "sid"))
            ):
                raise CredentialRejected("Session claims rejected")
            return VerifiedSession(
                issuer=self.issuer, audience=self.audience, subject=claims["sub"],
                session_id=claims["sid"], authorized_party=claims["azp"],
                issued_at=claims["iat"], expires_at=claims["exp"],
            )
        except (jwt.PyJWTError, KeyError, TypeError) as exc:
            raise CredentialRejected("Invalid session credential") from exc
