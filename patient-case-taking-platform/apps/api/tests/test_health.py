from collections.abc import Awaitable, Callable

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import health

client = TestClient(app)


def test_healthz_reports_process_liveness() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_returns_503_without_dependencies() -> None:
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


@pytest.mark.asyncio
async def test_readyz_reports_individual_dependency_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def healthy() -> None:
        return None

    async def unhealthy() -> None:
        raise ConnectionError("dependency unavailable")

    probes: dict[str, Callable[[], Awaitable[None]]] = {
        "_check_postgres": healthy,
        "_check_mongodb": unhealthy,
        "_check_redis": healthy,
    }
    for name, probe in probes.items():
        monkeypatch.setattr(health, name, probe)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"postgres": "ok", "mongodb": "unavailable", "redis": "ok"},
    }
