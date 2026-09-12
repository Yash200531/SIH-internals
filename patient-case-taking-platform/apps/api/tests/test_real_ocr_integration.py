"""Opt-in inference check for the real PP-OCRv5 provider."""

import io
import os
import re

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.ocr.fast_paddle_provider import FastPaddleOCRProvider

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REAL_OCR_INTEGRATION") != "1",
    reason="set RUN_REAL_OCR_INTEGRATION=1 in the dedicated OCR image",
)


def _clear_prescription_image() -> bytes:
    image = Image.new("RGB", (1600, 520), "white")
    font_path = os.getenv(
        "OCR_TEST_FONT",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    font = ImageFont.truetype(font_path, 64)
    draw = ImageDraw.Draw(image)
    draw.text((70, 60), "PRESCRIPTION", fill="black", font=font)
    draw.text((70, 190), "METFORMIN 500 MG", fill="black", font=font)
    draw.text((70, 320), "TAKE ONE TABLET DAILY", fill="black", font=font)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_real_ppocrv5_recognizes_a_clear_printed_prescription() -> None:
    provider = FastPaddleOCRProvider(language="en")
    await provider.warmup()
    result = await provider.recognize(_clear_prescription_image(), "image/png")

    normalized = re.sub(r"[^A-Z0-9]", "", result.text.upper())
    assert result.provider == "paddleocr_fast"
    assert result.model_version == "PP-OCRv5-mobile"
    assert result.regions
    assert "METFORMIN" in normalized
    assert "500" in normalized
