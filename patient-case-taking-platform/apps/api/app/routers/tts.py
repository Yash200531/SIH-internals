import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.tts.registry import get_active_provider

router = APIRouter(prefix="/api/v1/tts", tags=["tts"])


class SynthesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)
    language: Literal["hi", "en"] = "hi"
    voice: Literal["calm"] = "calm"


@router.post("/synthesize", response_class=Response)
async def synthesize_speech(body: SynthesisRequest) -> Response:
    try:
        provider = get_active_provider()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="TTS provider unavailable") from exc

    try:
        async with asyncio.timeout(settings.TTS_SYNTHESIS_TIMEOUT_SECONDS):
            audio = await provider.synthesize(text=body.text, language=body.language)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="TTS synthesis timed out") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid TTS synthesis request") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="TTS synthesis failed") from exc
    return Response(
        content=audio.content,
        media_type=audio.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-MediKiosk-TTS-Provider": audio.provider,
            "X-MediKiosk-TTS-Version": audio.provider_version,
            "X-MediKiosk-TTS-Language": body.language,
        },
    )
