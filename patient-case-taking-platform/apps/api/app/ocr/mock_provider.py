"""Deterministic OCR provider used for local development and contract tests."""

from app.ocr.base import OCRProvider, OCRRegion, OCRResult


class MockOCRProvider(OCRProvider):
    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_version(self) -> str:
        return "mock-ocr-v1"

    @property
    def language_pack_version(self) -> str:
        return "synthetic-en-v1"

    async def recognize(self, image_bytes: bytes, mime_type: str = "image/png") -> OCRResult:
        if not image_bytes:
            raise ValueError("Image file is empty")
        text = "Sample clinical document"
        return OCRResult(
            text=text,
            regions=[
                OCRRegion(
                    text=text,
                    confidence=1.0,
                    language="en",
                    script="Latn",
                    reading_order=1,
                )
            ],
            confidence=1.0,
            provider=self.provider_name,
            model_version=self.model_version,
            language_pack_version=self.language_pack_version,
            duration_ms=0,
        )
