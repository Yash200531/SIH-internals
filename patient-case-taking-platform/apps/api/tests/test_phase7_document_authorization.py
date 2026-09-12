"""Fail-closed consent/purpose authorization for document ingestion."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.documents.authorization import (
    ConsentAuthorizationDenied,
    PostgresDocumentPurposeAuthorizer,
)


class _Connection:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row
        self.tenant_context: str | None = None

    async def execute(self, _query: str, tenant_id: str) -> None:
        self.tenant_context = tenant_id

    async def fetchrow(self, _query: str, *_args: object) -> dict[str, object] | None:
        return self.row

    def transaction(self) -> "_Transaction":
        return _Transaction()


class _Acquire:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


def _scope() -> dict[str, object]:
    return {
        "tenant_id": uuid4(),
        "patient_id": uuid4(),
        "encounter_id": uuid4(),
        "purpose": "treatment",
        "consent_reference": str(uuid4()),
    }


@pytest.mark.asyncio
async def test_active_scoped_consent_authorizes_upload() -> None:
    scope = _scope()
    connection = _Connection(
        {
            "status": "granted",
            "expires_at": datetime.now(UTC) + timedelta(minutes=5),
            "purpose": scope["purpose"],
            "patient_id": scope["patient_id"],
            "encounter_id": scope["encounter_id"],
            "scope": {"document_upload": True},
        }
    )
    authorizer = PostgresDocumentPurposeAuthorizer(_Pool(connection))

    await authorizer.authorize(**scope)

    assert connection.tenant_context == str(scope["tenant_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    [
        None,
        {"status": "revoked", "scope": {"document_upload": True}},
        {
            "status": "granted",
            "expires_at": datetime.now(UTC) - timedelta(seconds=1),
            "scope": {"document_upload": True},
        },
        {"status": "granted", "expires_at": None, "scope": {}},
        {"status": "granted", "expires_at": None, "scope": "not-json"},
    ],
)
async def test_missing_revoked_expired_or_unscoped_consent_is_denied(
    row: dict[str, object] | None,
) -> None:
    authorizer = PostgresDocumentPurposeAuthorizer(_Pool(_Connection(row)))

    with pytest.raises(ConsentAuthorizationDenied):
        await authorizer.authorize(**_scope())


@pytest.mark.asyncio
async def test_malformed_consent_reference_is_denied_before_database_access() -> None:
    connection = _Connection(None)
    authorizer = PostgresDocumentPurposeAuthorizer(_Pool(connection))
    scope = _scope()
    scope["consent_reference"] = "not-a-uuid"

    with pytest.raises(ConsentAuthorizationDenied):
        await authorizer.authorize(**scope)

    assert connection.tenant_context is None
