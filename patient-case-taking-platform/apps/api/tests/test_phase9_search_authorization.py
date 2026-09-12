from uuid import uuid4

import pytest

from app.auth.token import TokenPayload
from app.search.authorization import SearchAuthorizationDenied, authorize_search_identity


def _token(role: str, *, user_id=None, tenant_id=None, facilities=None) -> TokenPayload:
    return TokenPayload(
        user_id=str(user_id or uuid4()),
        email=None,
        role=role,
        tenant_id=str(tenant_id or uuid4()),
        facility_ids=[str(value) for value in (facilities or [uuid4()])],
        issued_at=0,
        expires_at=1,
        token_hash="x",
    )


def test_patient_scope_is_always_derived_from_actor_identity() -> None:
    patient_id, facility_id = uuid4(), uuid4()
    identity = authorize_search_identity(
        _token("patient", user_id=patient_id, facilities=[facility_id]),
        requested_patient_id=uuid4(),
    )

    assert identity.patient_id == patient_id
    assert identity.facility_ids == frozenset({facility_id})


def test_staff_requires_patient_and_facility_subset() -> None:
    allowed, denied = uuid4(), uuid4()
    doctor = _token("doctor", facilities=[allowed])
    with pytest.raises(SearchAuthorizationDenied, match="Patient scope"):
        authorize_search_identity(doctor, requested_patient_id=None)
    with pytest.raises(SearchAuthorizationDenied, match="Facility access"):
        authorize_search_identity(
            doctor,
            requested_patient_id=uuid4(),
            requested_facility_ids={denied},
        )


@pytest.mark.parametrize("role", ["admin", "receptionist", "kiosk"])
def test_unsupported_roles_are_denied(role: str) -> None:
    with pytest.raises(SearchAuthorizationDenied, match="role"):
        authorize_search_identity(_token(role), requested_patient_id=uuid4())
