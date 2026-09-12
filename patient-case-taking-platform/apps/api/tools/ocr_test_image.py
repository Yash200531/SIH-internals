"""OCR test on a real prescription image.

Usage inside the OCR Docker container:
    python -m tools.ocr_test_image /path/to/image.jpg

The image is read from the path given as argv[1].
If no path is given, a synthetic prescription is generated instead.
"""

import asyncio
import io
import os
import re
import sys

from app.ocr.fast_paddle_provider import FastPaddleOCRProvider


def _load_image(path: str) -> tuple[bytes, str]:
    """Load image bytes and detect content type from extension."""
    ext = path.rsplit(".", 1)[-1].lower()
    mime = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }.get(ext, "image/jpeg")
    with open(path, "rb") as f:
        return f.read(), mime


def _synthetic_image() -> tuple[bytes, str]:
    """Generate a clear synthetic prescription for baseline testing."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1600, 700), "white")
    font_path = os.getenv(
        "OCR_TEST_FONT",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    font = ImageFont.truetype(font_path, 56)
    draw = ImageDraw.Draw(image)
    lines = [
        "PRESCRIPTION",
        "Patient: John Doe  Age: 45",
        "METFORMIN 500 MG - 1 tablet twice daily after meals",
        "AMLODIPINE 5 MG  - 1 tablet at night",
        "ATORVASTATIN 10 MG - 1 tablet at bedtime",
        "Dr. Sharma  |  Date: 10/09/2026",
    ]
    y = 40
    for line in lines:
        draw.text((60, y), line, fill="black", font=font)
        y += 90
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue(), "image/png"


async def run(image_path: str | None) -> None:
    if image_path:
        print(f"Loading image: {image_path}")
        img_bytes, mime = _load_image(image_path)
        print(f"Image size: {len(img_bytes):,} bytes  MIME: {mime}")
    else:
        print("No image path given — using synthetic prescription")
        img_bytes, mime = _synthetic_image()

    provider = FastPaddleOCRProvider(language="en")
    print("Warming up PP-OCRv5-mobile model ...")
    await provider.warmup()
    print("Running OCR ...")
    result = await provider.recognize(img_bytes, mime)

    print()
    print("=" * 60)
    print("OCR RESULT")
    print("=" * 60)
    print(f"Provider   : {result.provider}")
    print(f"Model      : {result.model_version}")
    print(f"Duration   : {result.duration_ms} ms")
    print(f"Regions    : {len(result.regions)}")
    print()
    print("--- Full extracted text ---")
    print(result.text if result.text.strip() else "(no text detected)")
    print()
    if result.regions:
        print("--- All regions (text | confidence) ---")
        for r in sorted(
            result.regions,
            key=lambda x: x.confidence if x.confidence is not None else 0.0,
            reverse=True,
        ):
            confidence = r.confidence if r.confidence is not None else 0.0
            bar = "█" * int(confidence * 20)
            print(f"  {confidence:.2f} {bar:<20} {r.text}")
    print("=" * 60)

    # Quick validation
    normalized = re.sub(r"[^A-Z0-9 ]", " ", result.text.upper())
    words = normalized.split()
    print(f"\nDetected {len(words)} words total")
    if len(words) > 3:
        print("PASS — OCR pipeline is working correctly")
    else:
        print("WARN — very few words detected, check image quality")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run(path))
