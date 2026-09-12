"""Voice context expiry and external-store isolation."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.asr.runtime import VoiceRuntime, VoiceTurnContext
from app.config import settings


def context():
    return VoiceTurnContext(
        tenant_id=uuid4(), session_id=uuid4(), encounter_id=uuid4(),
        consent_id=uuid4(), turn_id=uuid4(), language="en",
        retain_audio=False, audio_retention_consent=False,
    )


@pytest.mark.asyncio
async def test_local_context_expires_and_is_capacity_bounded(monkeypatch):
    monkeypatch.setattr(settings, "VOICE_REDIS_ENABLED", False)
    monkeypatch.setattr(settings, "VOICE_CONTEXT_TTL_SECONDS", 10)
    now = [100.0]
    monkeypatch.setattr("app.asr.runtime.time.monotonic", lambda: now[0])
    runtime = VoiceRuntime()
    first = context()
    await runtime.save_context(first, transcript="Synthetic transcript")
    assert str(first.turn_id) in runtime.contexts
    now[0] = 111.0
    assert runtime.contexts == {}
    for _ in range(150):
        await runtime.save_context(context(), status="recording")
    assert len(runtime.contexts) == 128


@pytest.mark.asyncio
async def test_redis_context_has_ttl_without_local_transcript_copy(monkeypatch):
    monkeypatch.setattr(settings, "VOICE_REDIS_ENABLED", True)
    client = AsyncMock()
    monkeypatch.setattr("redis.asyncio.from_url", lambda *_args: client)
    runtime = VoiceRuntime()
    turn = context()
    await runtime.save_context(turn, transcript="Synthetic transcript")
    assert runtime.contexts == {}
    assert client.setex.call_args.args[:2] == (
        f"voice:turn:{turn.turn_id}", settings.VOICE_CONTEXT_TTL_SECONDS,
    )
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_failure_closes_client_without_local_fallback(monkeypatch):
    monkeypatch.setattr(settings, "VOICE_REDIS_ENABLED", True)
    client = AsyncMock()
    client.setex.side_effect = ConnectionError("unavailable")
    monkeypatch.setattr("redis.asyncio.from_url", lambda *_args: client)
    runtime = VoiceRuntime()
    with pytest.raises(ConnectionError):
        await runtime.save_context(context(), transcript="Synthetic transcript")
    assert runtime.contexts == {}
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_local_event_history_is_bounded(monkeypatch):
    monkeypatch.setattr(settings, "VOICE_KAFKA_ENABLED", False)
    runtime = VoiceRuntime()
    for index in range(150):
        await runtime.publish("synthetic", {"sequence": index})
    assert len(runtime.events) == 128
    assert runtime.events[-1][1] == {"sequence": 149}
