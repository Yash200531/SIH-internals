import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.jwt_verifier import (
    ClerkSessionVerifier,
    CredentialRejected,
    IdentityProviderUnavailable,
)


@pytest.fixture(scope="module")
def keys():
    return [rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2)]


def public_key(key, kid):
    return {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())), "kid": kid, "alg": "RS256", "use": "sig"}


def token(key, kid="first", _omit=None, **changes):
    now = int(time.time())
    claims = {"iss": "https://identity.example.test", "aud": "patient-app", "sub": "user_test",
              "sid": "sess_test", "azp": "https://patient.example.test", "iat": now,
              "nbf": now - 1, "exp": now + 60, **changes}
    if _omit is not None:
        claims.pop(_omit)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def verifier(handler, clock=lambda: 100.0):
    return ClerkSessionVerifier(
        issuer="https://identity.example.test", audience="patient-app",
        authorized_parties=frozenset({"https://patient.example.test"}),
        transport=httpx.MockTransport(handler), clock=clock,
    )


async def test_signature_verified_and_external_roles_not_returned(keys):
    def response(request):
        assert str(request.url) == "https://identity.example.test/.well-known/jwks.json"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"keys": [public_key(keys[0], "first")]})
    subject = await verifier(response).verify(token(keys[0], role="admin", facility_ids=["forged"]))
    assert subject.subject == "user_test"
    assert subject.audience == "patient-app"
    assert not hasattr(subject, "role")
    assert not hasattr(subject, "facility_ids")


@pytest.mark.parametrize("change", [
    {"iss": "https://other.example.test"}, {"aud": "staff-app"}, {"aud": ["patient-app", "staff-app"]},
    {"azp": "https://attacker.example.test"}, {"exp": 1}, {"nbf": 9999999999}, {"iat": 9999999999},
    {"sub": ""}, {"sid": ""}, {"sts": "pending"}, {"act": {"sub": "impersonator"}},
])
async def test_cross_application_and_invalid_claims_rejected(keys, change):
    instance = verifier(lambda _: httpx.Response(200, json={"keys": [public_key(keys[0], "first")]}))
    with pytest.raises(CredentialRejected):
        await instance.verify(token(keys[0], **change))


async def test_forged_signature_and_algorithm_confusion_rejected(keys):
    instance = verifier(lambda _: httpx.Response(200, json={"keys": [public_key(keys[0], "first")]}))
    with pytest.raises(CredentialRejected):
        await instance.verify(token(keys[1]))
    with pytest.raises(CredentialRejected):
        await instance.verify(jwt.encode({"sub": "user_test"}, "attacker-secret-that-is-at-least-32-bytes", algorithm="HS256", headers={"kid": "first"}))


@pytest.mark.parametrize("required", ["iss", "aud", "sub", "sid", "azp", "iat", "nbf", "exp"])
async def test_required_session_claims_cannot_be_missing(keys, required):
    instance = verifier(lambda _: httpx.Response(200, json={"keys": [public_key(keys[0], "first")]}))
    with pytest.raises(CredentialRejected):
        await instance.verify(token(keys[0], _omit=required))


async def test_key_rotation_cache_expiry_outage_and_refresh_rate_bound(keys):
    clock = [100.0]
    state = {"keys": [public_key(keys[0], "first")], "calls": 0, "outage": False}

    def response(_):
        state["calls"] += 1
        return httpx.Response(503) if state["outage"] else httpx.Response(200, json={"keys": state["keys"]})

    instance = verifier(response, lambda: clock[0])
    await instance.verify(token(keys[0]))
    await instance.verify(token(keys[0]))
    assert state["calls"] == 1
    with pytest.raises(CredentialRejected):
        await instance.verify(token(keys[1], kid="rotated"))
    assert state["calls"] == 1
    state["keys"] = [public_key(keys[1], "rotated")]
    clock[0] += 6
    await instance.verify(token(keys[1], kid="rotated"))
    assert state["calls"] == 2
    state["outage"] = True
    clock[0] += 61
    with pytest.raises(IdentityProviderUnavailable):
        await instance.verify(token(keys[1], kid="rotated"))


@pytest.mark.parametrize("response", [httpx.Response(302, headers={"Location": "https://elsewhere.example.test"}), httpx.Response(200, content=b"x" * 65537), httpx.Response(200, json={"keys": []})])
async def test_redirect_oversized_and_invalid_jwks_fail_closed(keys, response):
    instance = verifier(lambda _: response)
    with pytest.raises(IdentityProviderUnavailable):
        await instance.verify(token(keys[0]))


async def test_duplicate_key_id_is_not_silently_selected(keys):
    instance = verifier(lambda _: httpx.Response(200, json={"keys": [public_key(key, "first") for key in keys]}))
    with pytest.raises(IdentityProviderUnavailable):
        await instance.verify(token(keys[0]))
