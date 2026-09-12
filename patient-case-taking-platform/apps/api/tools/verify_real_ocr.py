"""Run an assertion-based PP-OCRv5 inference check inside the OCR image."""

import asyncio
import io
import os
import re

from PIL import Image, ImageDraw, ImageFont

from app.ocr.fast_paddle_provider import FastPaddleOCRProvider


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


async def verify() -> None:
    provider = FastPaddleOCRProvider(language="en")
    await provider.warmup()
    result = await provider.recognize(_clear_prescription_image(), "image/png")
    normalized = re.sub(r"[^A-Z0-9]", "", result.text.upper())
    if not result.regions or "METFORMIN" not in normalized or "500" not in normalized:
        raise RuntimeError(f"PP-OCRv5 verification failed: {result.text!r}")
    print(
        f"PASS provider={result.provider} model={result.model_version} "
        f"regions={len(result.regions)} duration_ms={result.duration_ms}"
    )


if __name__ == "__main__":
    asyncio.run(verify())
