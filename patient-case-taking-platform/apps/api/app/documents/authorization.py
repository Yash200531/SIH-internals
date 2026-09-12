"""Purpose-bound consent authorization for clinical document uploads."""

import json
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

_GET_CONSENT = """
SELECT patient_id, encounter_id, purpose, status, scope, expires_at
FROM consent_artifact
WHERE tenant_id = $1 AND id = $2
"""


class ConsentAuthorizationDenied(PermissionError):
    """Raised without detail when a consent reference cannot authorize an upload."""


class DocumentPurposeAuthorizer(Protocol):
    async def authorize(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        encounter_id: UUID,
        purpose: str,
        consent_reference: str,
    ) -> None: ...


class PostgresDocumentPurposeAuthorizer:
    """Validate an active, purpose- and encounter-scoped durable consent grant."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def authorize(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        encounter_id: UUID,
        purpose: str,
        consent_reference: str,
    ) -> None:
        try:
            consent_id = UUID(consent_reference)
        except (TypeError, ValueError) as exc:
            raise ConsentAuthorizationDenied from exc

        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
                )
                row = await connection.fetchrow(_GET_CONSENT, tenant_id, consent_id)

        if row is None:
            raise ConsentAuthorizationDenied
        expires_at = row.get("expires_at")
        scope = row.get("scope") or {}
        if isinstance(scope, str):
            try:
                scope = json.loads(scope)
            except json.JSONDecodeError:
                scope = {}
        is_authorized = (
            row.get("status") == "granted"
            and row.get("patient_id") == patient_id
            and row.get("encounter_id") == encounter_id
            and row.get("purpose") == purpose
            and isinstance(scope, dict)
            and scope.get("document_upload") is True
            and (expires_at is None or expires_at > datetime.now(UTC))
        )
        if not is_authorized:
            raise ConsentAuthorizationDenied
