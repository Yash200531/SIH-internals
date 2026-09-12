"""ASR provider abstraction.
Any speech-to-text backend implements this interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class TranscriptionChunk:
    text: str
    confidence: float | None  # None when the provider does not expose a calibrated score
    is_final: bool
    language: str | None = None
    speaker: str | None = None


@dataclass
class TranscriptionResult:
    text: str
    confidence: float | None
    language: str
    chunks: list[TranscriptionChunk]
    duration_ms: int
    provider: str


class ASRProvider(ABC):
    """Base class for ASR providers."""

    @abstractmethod
    def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: str = "hi",
        sample_rate: int = 16000,
    ) -> AsyncIterator[TranscriptionChunk]:
        """Stream transcription from audio chunks."""
        ...

    @abstractmethod
    async def transcribe_file(
        self,
        audio_bytes: bytes,
        language: str = "hi",
        sample_rate: int = 16000,
    ) -> TranscriptionResult:
        """Transcribe a complete audio file."""
        ...

    @abstractmethod
    async def detect_language(self, audio_bytes: bytes) -> str:
        """Detect the language of audio."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...
