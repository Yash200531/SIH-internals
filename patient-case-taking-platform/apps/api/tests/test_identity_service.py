import pytest
from fastapi import HTTPException

from app.auth import service
from app.auth.token import create_dev_token


async def test_production_cannot_accept_demo_credentials(monkeypatch):
    monkeypatch.setattr(service.settings, "APP_ENV", "production")
    monkeypatch.setattr(service.settings, "AUTH_PROVIDER", "demo")
    token = create_dev_token("demo", None, "admin", "demo", ["demo"])
    with pytest.raises(HTTPException) as error:
        await service.authenticate_token(token)
    assert error.value.status_code == 503


async def test_clerk_provider_does_not_fall_back_to_demo(monkeypatch):
    monkeypatch.setattr(service.settings, "AUTH_PROVIDER", "clerk")
    monkeypatch.setattr(service.settings, "CLERK_APPLICATIONS_JSON", "[]")
    with pytest.raises(HTTPException) as error:
        await service.authenticate_token(create_dev_token("demo", None, "admin", "demo", ["demo"]))
    assert error.value.status_code == 503
