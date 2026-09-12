"""Bounded REST and WebSocket endpoints for speech-to-text."""
import asyncio
import io
import json
import logging
import time
import wave
from hashlib import sha256
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)

from app.asr.authorization import authorize_voice
from app.asr.quality import analyze_pcm16
from app.asr.registry import get_provider_for_language
from app.asr.runtime import RetentionUnavailable, VoiceTurnContext, voice_runtime
from app.audit.emitter import audit_emitter
from app.config import settings

router = APIRouter(tags=["asr"])
logger = logging.getLogger(__name__)
MAX_AUDIO_BYTES = 15 * 1024 * 1024
ALLOWED_AUDIO_TYPES = {
    "audio/wav", "audio/x-wav", "audio/webm", "audio/ogg", "audio/mpeg", "audio/mp4"
}


async def _authenticate_socket(websocket: WebSocket) -> str:
    """Browser credentials travel in the first frame, never in a logged URL."""
    try:
        frame = await asyncio.wait_for(websocket.receive_json(), timeout=10)
    except (TimeoutError, ValueError, KeyError) as exc:
        raise HTTPException(401, "Patient authentication required") from exc
    if not isinstance(frame, dict) or frame.get("type") != "authenticate":
        raise HTTPException(401, "Patient authentication required")
    token = frame.get("access_token")
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise HTTPException(401, "Patient authentication required")
    return token


def _pcm16_to_wav(pcm: bytes, sample_rate: int = 16_000) -> bytes:
    """Wrap mono signed 16-bit PCM in one valid WAV container."""
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()


@router.websocket("/ws/asr")
async def asr_stream(
    websocket: WebSocket,
    language: str = "hi",
    tenant_id: UUID | None = None,
    session_id: UUID | None = None,
    encounter_id: UUID | None = None,
    consent_id: UUID | None = None,
    retain_audio: bool = False,
    audio_retention_consent: bool = False,
):
    """WebSocket endpoint for streaming ASR.

    Client sends: raw audio bytes (PCM 16-bit, 16kHz)
    Server sends: JSON transcription chunks

    Protocol:
    1. Client connects with ?language=hi
    2. Client sends authenticate frame with access_token, waits for ready, then PCM
    3. Client sends {"type": "end"} to signal end of audio
    4. Server sends transcription chunks as JSON
    5. Server sends {"type": "done", "result": {...}} when complete
    """
    await websocket.accept()
    start_time = time.monotonic()
    audio = bytearray()
    last_partial_size = 0
    turn_id = uuid4()

    if (
        tenant_id is None
        or session_id is None
        or encounter_id is None
        or consent_id is None
    ):
        await websocket.send_json({
            "type": "error",
            "code": "voice_context_required",
            "detail": "Voice session, encounter, tenant, and consent identifiers are required",
            "fallback": "touch",
        })
        await websocket.close(code=1008)
        return

    try:
        token = await _authenticate_socket(websocket)
        patient_id = await authorize_voice(token, tenant_id, encounter_id, consent_id, retain_audio, session_id=session_id)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({
            "type": "error", "code": "voice_access_denied",
            "detail": exc.detail if isinstance(exc, HTTPException) else "Voice authorization unavailable",
            "fallback": "touch",
        })
        await websocket.close(code=1008)
        return

    try:
        provider = get_provider_for_language(language)
    except ValueError as exc:
        await websocket.send_json({
            "type": "error",
            "code": "unsupported_language",
            "detail": str(exc),
            "fallback": "touch",
        })
        await websocket.close(code=1008)
        return

    except Exception:
        logger.error("ASR provider initialization failed")
        await websocket.send_json({
            "type": "error",
            "code": "asr_unavailable",
            "detail": "Transcription service unavailable",
            "fallback": "touch",
        })
        await websocket.close(code=1011)
        return

    context = VoiceTurnContext(
        tenant_id=tenant_id,
        session_id=session_id,
        encounter_id=encounter_id,
        consent_id=consent_id,
        turn_id=turn_id,
        language=language,
        retain_audio=retain_audio,
        audio_retention_consent=audio_retention_consent,
    )
    try:
        await voice_runtime.save_context(context, status="recording")
        await websocket.send_json({"type": "ready", "turn_id": str(turn_id)})
        while True:
            message = await websocket.receive()
            if message.get("bytes") is not None:
                chunk = message["bytes"]
                if len(audio) + len(chunk) > MAX_AUDIO_BYTES:
                    await websocket.send_json({"type": "error", "detail": "Audio exceeds 15 MB limit"})
                    await websocket.close(code=1009)
                    return
                audio.extend(chunk)
                if len(audio) - last_partial_size >= settings.ASR_PARTIAL_INTERVAL_BYTES:
                    quality = analyze_pcm16(bytes(audio))
                    if quality.has_speech:
                        await authorize_voice(token, tenant_id, encounter_id, consent_id, retain_audio, session_id=session_id)
                        partial = await provider.transcribe_file(
                            _pcm16_to_wav(bytes(audio)),
                            language=language,
                        )
                        await authorize_voice(token, tenant_id, encounter_id, consent_id, retain_audio, session_id=session_id)
                        await websocket.send_json({
                            "type": "transcript",
                            "text": partial.text,
                            "confidence": partial.confidence,
                            "signal_quality": quality.as_dict(),
                            "is_final": False,
                            "language": partial.language,
                        })
                        await voice_runtime.save_context(
                            context,
                            status="recording",
                            interim_transcript=partial.text,
                            signal_quality=quality.as_dict(),
                        )
                    last_partial_size = len(audio)
            elif message.get("text") is not None:
                try:
                    command = json.loads(message["text"])
                except json.JSONDecodeError:
                    await websocket.send_json({"type": "error", "detail": "Invalid control message"})
                    continue
                if not isinstance(command, dict):
                    await websocket.send_json({"type": "error", "detail": "Invalid control message"})
                    continue
                if command.get("type") == "end":
                    break

        if not audio:
            await websocket.send_json({"type": "error", "detail": "No audio received"})
            return

        await authorize_voice(token, tenant_id, encounter_id, consent_id, retain_audio, session_id=session_id)
        quality = analyze_pcm16(bytes(audio))
        result = await provider.transcribe_file(_pcm16_to_wav(bytes(audio)), language=language)
        low_model_confidence = (
            result.confidence is not None and result.confidence < settings.ASR_MIN_CONFIDENCE
        )
        needs_clarification = (
            not result.text.strip()
            or quality.score < settings.ASR_MIN_SIGNAL_QUALITY
            or low_model_confidence
        )
        await authorize_voice(token, tenant_id, encounter_id, consent_id, retain_audio, session_id=session_id)
        object_key = await voice_runtime.retain(context, bytes(audio))
        transcript_hash = sha256(result.text.encode()).hexdigest()
        audio_hash = sha256(audio).hexdigest()
        processing_ms = int((time.monotonic() - start_time) * 1000)
        await voice_runtime.save_context(
            context,
            status="complete",
            transcript=result.text,
            confidence=result.confidence,
            signal_quality=quality.as_dict(),
            needs_clarification=needs_clarification,
            retained_object_key=object_key,
        )
        await voice_runtime.publish(
            "ai.asr.completed.v1",
            {
                **context.metadata(),
                "audio_sha256": audio_hash,
                "transcript_sha256": transcript_hash,
                "provider": result.provider,
                "processing_ms": processing_ms,
                "needs_clarification": needs_clarification,
                "retained_object_key": object_key,
            },
        )
        await websocket.send_json({
            "type": "transcript",
            "text": result.text,
            "confidence": result.confidence,
            "signal_quality": quality.as_dict(),
            "needs_clarification": needs_clarification,
            "is_final": True,
            "language": result.language,
        })

        await websocket.send_json({
            "type": "done",
            "result": {
                "text": result.text,
                "confidence": result.confidence,
                "language": result.language,
                "processing_ms": processing_ms,
                "provider": result.provider,
                "turn_id": str(turn_id),
                "needs_clarification": needs_clarification,
                "signal_quality": quality.as_dict(),
            },
        })

        audit_emitter.emit(
            tenant_id=tenant_id,
            actor_id=patient_id,
            actor_type="kiosk",
            actor_role=None,
            action="asr_transcribe",
            resource_type="voice_turn",
            resource_id=turn_id,
            purpose="treatment",
            outcome="success",
            audit_metadata={
                "session_id": str(session_id),
                "encounter_id": str(encounter_id),
                "consent_id": str(consent_id),
                "retain_audio": retain_audio,
                "audio_retention_consent": audio_retention_consent,
                "retained_object_key": object_key,
                "audio_sha256": audio_hash,
                "transcript_sha256": transcript_hash,
                "provider": result.provider,
                "language": result.language,
                "needs_clarification": needs_clarification,
                "signal_quality": quality.as_dict(),
            },
        )

    except WebSocketDisconnect:
        return
    except HTTPException as exc:
        await websocket.send_json({
            "type": "error", "code": "voice_access_denied",
            "detail": exc.detail, "fallback": "touch",
        })
        await websocket.close(code=1008)
    except RetentionUnavailable as exc:
        await websocket.send_json({
            "type": "error",
            "code": "audio_retention_unavailable",
            "detail": str(exc),
            "fallback": "touch",
        })
    except ValueError as exc:
        await websocket.send_json({
            "type": "error", "detail": str(exc), "fallback": "touch"
        })
    except Exception:
        logger.exception("ASR WebSocket processing failed")
        try:
            await websocket.send_json({
                "type": "error",
                "detail": "Transcription failed",
                "fallback": "touch",
            })
        except Exception:
            pass


# REST fallback for non-streaming transcription
@router.post("/api/v1/asr/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = Form("hi"),
    tenant_id: UUID = Form(...),
    session_id: UUID = Form(...),
    encounter_id: UUID = Form(...),
    consent_id: UUID = Form(...),
    authorization: str = Header(""),
):
    """Transcribe one uploaded audio file."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "Bearer authorization required")
    await authorize_voice(token.strip(), tenant_id, encounter_id, consent_id, session_id=session_id)
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio type")
    audio = await file.read(MAX_AUDIO_BYTES + 1)
    if not audio:
        raise HTTPException(status_code=400, detail="Audio file is empty")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio exceeds 15 MB limit")
    try:
        result = await get_provider_for_language(language).transcribe_file(
            audio, language=language
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("ASR transcription failed")
        raise HTTPException(status_code=503, detail="Transcription service unavailable") from exc
    await authorize_voice(token.strip(), tenant_id, encounter_id, consent_id, session_id=session_id)
    return {
        "text": result.text,
        "confidence": result.confidence,
        "language": result.language,
        "processing_ms": result.duration_ms,
        "provider": result.provider,
    }
