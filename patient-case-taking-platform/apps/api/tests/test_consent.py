from uuid import uuid4

from app.models.consent_artifact import ConsentArtifact


def _make_consent(**overrides) -> ConsentArtifact:
    defaults = {
        "tenant_id": uuid4(),
        "patient_id": uuid4(),
        "purpose": "treatment",
        "scope": {"categories": ["vitals"]},
    }
    defaults.update(overrides)
    return ConsentArtifact(**defaults)


def test_create_consent():
    consent = _make_consent()
    assert consent.status == "granted"
    assert consent.version == 1
    assert consent.purpose == "treatment"


def test_revoke_consent_creates_new_version():
    original = _make_consent()
    assert original.status == "granted"

    original.status = "revoked"
    revoked = ConsentArtifact(
        tenant_id=original.tenant_id,
        patient_id=original.patient_id,
        purpose=original.purpose,
        scope=original.scope,
        granted_by=original.granted_by,
        status="revoked",
        revoked_at=None,
        revoke_reason="patient request",
        previous_version_id=original.id,
        version=original.version + 1,
    )
    assert revoked.status == "revoked"
    assert revoked.version == 2
    assert revoked.previous_version_id == original.id
    assert original.status == "revoked"


def test_expired_consent_check():
    from datetime import datetime, timedelta, timezone

    consent = _make_consent(expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    assert consent.expires_at < datetime.now(timezone.utc)
