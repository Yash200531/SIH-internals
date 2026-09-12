import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as redis
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "0.1.0",
        "document_automation": {
            "ocr_enabled": settings.DOCUMENT_OCR_AUTOMATION_ENABLED,
            "extraction_enabled": settings.DOCUMENT_EXTRACTION_AUTOMATION_ENABLED,
        },
    }


@router.get("/readyz")
async def readyz():
    probes: dict[str, Callable[[], Awaitable[None]]] = {
        "postgres": _check_postgres,
        "mongodb": _check_mongodb,
        "redis": _check_redis,
    }
    results = await asyncio.gather(*(_run_probe(probe) for probe in probes.values()))
    checks = dict(zip(probes, results, strict=True))
    ready = all(result == "ok" for result in checks.values())
    payload = {"status": "ok" if ready else "unavailable", "checks": checks}

    if ready:
        return payload
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)


async def _run_probe(probe: Callable[[], Awaitable[None]]) -> str:
    try:
        await asyncio.wait_for(probe(), timeout=settings.READINESS_TIMEOUT_SECONDS)
    except Exception:
        return "unavailable"
    return "ok"


async def _check_postgres() -> None:
    connection = await asyncpg.connect(settings.DATABASE_URL)
    try:
        await connection.execute("SELECT 1")
    finally:
        await connection.close()


async def _check_mongodb() -> None:
    client: AsyncIOMotorClient[dict] = AsyncIOMotorClient(
        settings.MONGODB_URL,
        serverSelectionTimeoutMS=int(settings.READINESS_TIMEOUT_SECONDS * 1000),
    )
    try:
        await client.admin.command("ping")
    finally:
        client.close()


async def _check_redis() -> None:
    client: redis.Redis = redis.from_url(settings.REDIS_URL)
    try:
        await client.ping()
    finally:
        await client.aclose()
