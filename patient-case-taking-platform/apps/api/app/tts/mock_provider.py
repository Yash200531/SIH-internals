"""Deterministic offline audio used to exercise the complete speech loop."""

import hashlib
import io
import math
import struct
import wave

from app.tts.base import SpeechAudio


class MockTTSProvider:
    """Create a bounded WAV cue without a model, API key, or network call.

    The cue is intentionally not represented as intelligible speech. It proves
    the transport/playback contract while making the mock impossible to mistake
    for a production voice provider.
    """

    name = "mock"
    version = "mock-tone-v1"
    sample_rate = 16_000

    async def synthesize(self, *, text: str, language: str) -> SpeechAudio:
        digest = hashlib.sha256(f"{language}:{text}".encode()).digest()
        frames = bytearray()
        tone_frames = int(self.sample_rate * 0.07)
        pause_frames = int(self.sample_rate * 0.025)
        base_frequency = 360 if language == "hi" else 440

        for value in digest[: min(12, max(4, len(text) // 24 + 4))]:
            frequency = base_frequency + (value % 7) * 35
            for index in range(tone_frames):
                envelope = min(1.0, index / 120, (tone_frames - index) / 120)
                sample = int(
                    5_000
                    * envelope
                    * math.sin(2 * math.pi * frequency * index / self.sample_rate)
                )
                frames.extend(struct.pack("<h", sample))
            frames.extend(b"\x00\x00" * pause_frames)

        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(self.sample_rate)
            audio.writeframes(bytes(frames))
        return SpeechAudio(
            content=output.getvalue(),
            media_type="audio/wav",
            provider=self.name,
            provider_version=self.version,
        )
