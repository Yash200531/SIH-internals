"""PHI-free document pipeline operations and reconciliation tests."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.token import create_dev_token
from app.documents.dependencies import get_document_operations_repository
from app.documents.operations import DocumentOperationalSnapshot
from app.main import app

client = TestClient(app)


class _Repository:
    def __init__(self) -> None:
        self.tenant_id = uuid4()
        self.calls = 0

    async def snapshot(self, tenant_id):
        self.calls += 1
        assert tenant_id == self.tenant_id
        return DocumentOperationalSnapshot(
            review_backlog=4,
            oldest_review_age_seconds=901,
            scan_rejected=1,
            processing_failed=2,
            ocr_dead_letter=0,
            extraction_dead_letter=1,
            unpublished_events=3,
            event_dead_letter=0,
            projection_reconciliation_issues=0,
        )


@pytest.fixture
def repository() -> _Repository:
    value = _Repository()
    app.dependency_overrides[get_document_operations_repository] = lambda: value
    yield value
    app.dependency_overrides.pop(get_document_operations_repository, None)


def _headers(repository: _Repository, role: str) -> dict[str, str]:
    token = create_dev_token(
        str(uuid4()),
        "operator@example.test",
        role,
        str(repository.tenant_id),
        [str(uuid4())],
    )
    return {"Authorization": f"Bearer {token}"}


def test_admin_can_read_phi_free_pipeline_status(repository: _Repository) -> None:
    response = client.get(
        "/api/v1/document-operations/status",
        headers=_headers(repository, "admin"),
    )

    assert response.status_code == 200
    assert response.json()["review_backlog"] == 4
    assert response.json()["projection_reconciliation_issues"] == 0
    assert "patient" not in response.text.lower()
    assert "document_id" not in response.text


def test_clinician_cannot_read_tenant_operations(repository: _Repository) -> None:
    response = client.get(
        "/api/v1/document-operations/status",
        headers=_headers(repository, "doctor"),
    )

    assert response.status_code == 403
    assert repository.calls == 0


def test_health_exposes_automation_switch_state_without_phi() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["document_automation"] == {
        "ocr_enabled": True,
        "extraction_enabled": True,
    }
