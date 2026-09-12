from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SpeechAudio:
    content: bytes
    media_type: str
    provider: str
    provider_version: str


class TTSProvider(Protocol):
    name: str
    version: str

    async def synthesize(self, *, text: str, language: str) -> SpeechAudio: ...
