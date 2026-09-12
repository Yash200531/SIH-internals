"""OCR provider abstraction.
Any OCR backend implements this interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class OCRRegion:
    text: str
    confidence: float | None
    bbox: tuple[int, int, int, int] | None = None  # x1, y1, x2, y2
    language: str | None = None
    polygon: tuple[tuple[int, int], ...] | None = None
    script: str | None = None
    reading_order: int | None = None


@dataclass
class OCRResult:
    text: str
    regions: list[OCRRegion]
    confidence: float | None
    provider: str
    model_version: str
    language_pack_version: str
    duration_ms: int
    schema_version: str = "ocr-provider-result.v2"
    warnings: tuple[str, ...] = ()


class OCRProvider(ABC):
    """Base class for OCR providers."""

    @abstractmethod
    async def recognize(self, image_bytes: bytes, mime_type: str = "image/png") -> OCRResult:
        """Recognize text in an image."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    @property
    @abstractmethod
    def model_version(self) -> str:
        ...

    @property
    @abstractmethod
    def language_pack_version(self) -> str:
        ...
