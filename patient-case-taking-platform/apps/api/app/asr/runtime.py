"""Ephemeral context, metadata events, and consent-controlled audio retention."""

import asyncio
import base64
import json
import os
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from app.config import settings


class RetentionUnavailable(RuntimeError):
    """Raised when requested audio retention cannot be performed safely."""


@dataclass(frozen=True)
class VoiceTurnContext:
    tenant_id: UUID
    session_id: UUID
    encounter_id: UUID
    consent_id: UUID
    turn_id: UUID
    language: str
    retain_audio: bool
    audio_retention_consent: bool

    def metadata(self) -> dict[str, str | bool]:
        values = asdict(self)
        return {key: str(value) if isinstance(value, UUID) else value for key, value in values.items()}


class VoiceRuntime:
    """Infrastructure adapter with memory fallbacks for deterministic development."""

    def __init__(self) -> None:
        self._contexts: dict[str, dict[str, Any]] = {}
        self._expires: dict[str, float] = {}
        self.events: deque[tuple[str, dict[str, Any]]] = deque(maxlen=128)

    @property
    def contexts(self) -> dict[str, dict[str, Any]]:
        """Local test/development state, lazily expired and bounded on insertion."""
        now = time.monotonic()
        for key, deadline in list(self._expires.items()):
            if deadline <= now or key not in self._contexts:
                self._contexts.pop(key, None)
                self._expires.pop(key, None)
        return self._contexts

    async def save_context(self, context: VoiceTurnContext, **state: Any) -> None:
        payload = {**context.metadata(), **state}
        if not settings.VOICE_REDIS_ENABLED:
            contexts = self.contexts
            key = str(context.turn_id)
            if key not in contexts and len(contexts) >= 128:
                oldest = next(iter(contexts))
                contexts.pop(oldest)
                self._expires.pop(oldest, None)
            contexts[key] = payload
            self._expires[key] = time.monotonic() + settings.VOICE_CONTEXT_TTL_SECONDS
            return
        import redis.asyncio as redis

        client = redis.from_url(settings.REDIS_URL)
        try:
            await client.setex(
                f"voice:turn:{context.turn_id}",
                settings.VOICE_CONTEXT_TTL_SECONDS,
                json.dumps(payload, ensure_ascii=False),
            )
        finally:
            await client.aclose()

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        if not settings.VOICE_KAFKA_ENABLED:
            self.events.append((topic, payload))
            return
        from aiokafka import AIOKafkaProducer

        producer = AIOKafkaProducer(
            bootstrap_servers=[item.strip() for item in settings.KAFKA_BROKERS.split(",")],
            enable_idempotence=True,
        )
        await producer.start()
        try:
            await producer.send_and_wait(
                topic,
                json.dumps(payload, separators=(",", ":")).encode(),
            )
        finally:
            await producer.stop()

    async def retain(self, context: VoiceTurnContext, audio: bytes) -> str | None:
        if not context.retain_audio:
            return None
        if not context.audio_retention_consent:
            raise RetentionUnavailable("Explicit audio-retention consent is required")
        if not settings.AUDIO_RETENTION_ENABLED:
            raise RetentionUnavailable("Encrypted audio retention is unavailable")

        key_bytes = _decode_key(settings.AUDIO_ENCRYPTION_KEY)
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = os.urandom(12)
        associated_data = str(context.turn_id).encode()
        ciphertext = nonce + AESGCM(key_bytes).encrypt(nonce, audio, associated_data)
        object_key = (
            f"voice/{context.tenant_id}/{context.encounter_id}/{context.turn_id}.aesgcm"
        )

        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
        )
        try:
            await asyncio.to_thread(
                client.put_object,
                Bucket=settings.S3_BUCKET,
                Key=object_key,
                Body=ciphertext,
                ContentType="application/octet-stream",
                Metadata={"encryption": "AES-256-GCM", "retention-class": "consented-audio"},
            )
        finally:
            client.close()
        return object_key


def _decode_key(value: str) -> bytes:
    try:
        key = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise RetentionUnavailable("A valid base64 audio encryption key is required") from exc
    if len(key) != 32:
        raise RetentionUnavailable("Audio encryption key must contain 32 bytes")
    return key


voice_runtime = VoiceRuntime()
