"""OCR provider selection with real OCR by default and explicit test overrides."""

from app.config import settings
from app.ocr.base import OCRProvider
from app.ocr.mock_provider import MockOCRProvider

_provider: OCRProvider | None = None


def get_active_provider() -> OCRProvider:
    global _provider
    if _provider is not None:
        return _provider
    if settings.OCR_PROVIDER == "mock":
        if settings.APP_ENV not in {"development", "test"}:
            raise RuntimeError("Mock OCR provider is development-only")
        _provider = MockOCRProvider()
    elif settings.OCR_PROVIDER == "paddleocr_fast":
        from app.ocr.fast_paddle_provider import FastPaddleOCRProvider

        _provider = FastPaddleOCRProvider()
    elif settings.OCR_PROVIDER == "paddleocr_vl":
        if not settings.OCR_ALLOW_COMPLEX_LAYOUT_PROVIDER:
            raise RuntimeError("PaddleOCR-VL is not approved for automatic routing")
        from app.ocr.paddle_provider import PaddleOCRProvider

        _provider = PaddleOCRProvider()
    else:
        raise RuntimeError(f"Unknown OCR provider: {settings.OCR_PROVIDER}")
    return _provider


def set_active_provider(provider: OCRProvider | None) -> None:
    """Override provider in tests; pass None to return to configured selection."""
    global _provider
    _provider = provider
