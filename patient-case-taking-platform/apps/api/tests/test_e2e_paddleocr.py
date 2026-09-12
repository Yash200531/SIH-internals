"""E2E test for PaddleOCR-VL using native paddleocr library."""
import os
from pathlib import Path

import pytest

if os.getenv("RUN_AI_INTEGRATION_TESTS") != "1":
    pytest.skip("set RUN_AI_INTEGRATION_TESTS=1 to run model integration tests", allow_module_level=True)

import time

from PIL import Image, ImageDraw

# Create a test image with text
img = Image.new("RGB", (400, 200), "white")
draw = ImageDraw.Draw(img)
draw.text((20, 30), "Patient Name: Ramesh Kumar", fill="black")
draw.text((20, 70), "Age: 45", fill="black")
draw.text((20, 110), "Diagnosis: Type 2 Diabetes", fill="black")
draw.text((20, 150), "Rx: Metformin 500mg", fill="black")
test_img_path = Path(__file__).with_name("test_ocr_image.png")
img.save(test_img_path)
print(f"Created test image: {test_img_path}")

# Test via native paddleocr
print("\n=== PaddleOCR-VL E2E Test (native paddleocr) ===")
print("Loading pipeline...")
start = time.time()

from paddleocr import PaddleOCRVL  # noqa: E402

pipeline = PaddleOCRVL(pipeline_version="v1")
print(f"Pipeline loaded in {time.time()-start:.1f}s")

# Run OCR
print("\n--- Running OCR ---")
start = time.time()
output = pipeline.predict(str(test_img_path))

ocr_time = time.time() - start
print(f"OCR time: {ocr_time:.1f}s")

for res in output:
    res.print()
    if hasattr(res, "rec_texts") and res.rec_texts:
        print(f"\nRecognized {len(res.rec_texts)} text regions:")
        for i, (txt, score) in enumerate(zip(res.rec_texts, res.rec_scores)):
            print(f"  [{i}] {txt} (confidence: {score:.3f})")

print("\n=== PaddleOCR-VL: PASS ===")
