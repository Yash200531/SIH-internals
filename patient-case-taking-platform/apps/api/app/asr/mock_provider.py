"""Mock ASR provider for demo and testing.
Simulates transcription with realistic delay and output."""
import asyncio
import random
from typing import AsyncIterator

from app.asr.base import ASRProvider, TranscriptionChunk, TranscriptionResult

# Simulated patient responses by language
MOCK_RESPONSES = {
    "hi": [
        "मुझे दो दिन से बुखार है",
        "सिर में बहुत दर्द हो रहा है",
        "मुझे खांसी हो रही है",
        "पेट में दर्द है",
        "मेरा सीना भारी है",
        "शरीर में बहुत दर्द है",
        "मुझे सांस लेने में तकलीफ हो रही है",
        "कल रात से बुखार है",
        "दवाई खाने के बाद भी बुखार नहीं उतर रहा",
    ],
    "en": [
        "I have had fever for two days",
        "I have a severe headache",
        "I have been coughing since yesterday",
        "I have stomach pain",
        "My chest feels heavy",
        "My whole body aches",
        "I am having difficulty breathing",
        "The fever started last night",
        "The fever is not going down even after medicine",
    ],
}


class MockASRProvider(ASRProvider):
    """Mock provider that simulates ASR with realistic responses."""

    def __init__(self, error_rate: float = 0.05):
        self.error_rate = error_rate

    @property
    def provider_name(self) -> str:
        return "mock"

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: str = "hi",
        sample_rate: int = 16000,
    ) -> AsyncIterator[TranscriptionChunk]:
        """Simulate streaming transcription with word-by-word output."""
        # Consume the audio stream
        total_bytes = 0
        async for chunk in audio_stream:
            total_bytes += len(chunk)

        # Simulate processing delay based on audio length
        await asyncio.sleep(min(0.5, total_bytes / 100000))

        # Pick a mock response
        responses = MOCK_RESPONSES.get(language, MOCK_RESPONSES["hi"])
        text = random.choice(responses)
        words = text.split()

        # Stream word by word
        for i, word in enumerate(words):
            confidence = random.uniform(0.85, 0.99)
            if random.random() < self.error_rate:
                confidence = random.uniform(0.4, 0.7)

            is_final = i == len(words) - 1
            await asyncio.sleep(random.uniform(0.05, 0.15))

            yield TranscriptionChunk(
                text=" ".join(words[:i + 1]),
                confidence=confidence,
                is_final=is_final,
                language=language,
            )

    async def transcribe_file(
        self,
        audio_bytes: bytes,
        language: str = "hi",
        sample_rate: int = 16000,
    ) -> TranscriptionResult:
        """Transcribe a complete audio file."""
        await asyncio.sleep(0.3)  # simulate processing

        responses = MOCK_RESPONSES.get(language, MOCK_RESPONSES["hi"])
        text = random.choice(responses)

        return TranscriptionResult(
            text=text,
            confidence=random.uniform(0.88, 0.98),
            language=language,
            chunks=[TranscriptionChunk(text=text, confidence=0.95, is_final=True, language=language)],
            duration_ms=random.randint(1500, 4000),
            provider="mock",
        )

    async def detect_language(self, audio_bytes: bytes) -> str:
        """Mock language detection."""
        await asyncio.sleep(0.1)
        return random.choice(["hi", "en"])
