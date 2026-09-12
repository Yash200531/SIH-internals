"""OCR-only smoke test — isolate from ASR."""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

if os.getenv("RUN_SERVER_SMOKE_TESTS") != "1":
    pytest.skip("set RUN_SERVER_SMOKE_TESTS=1 to run subprocess smoke tests", allow_module_level=True)

import requests  # noqa: E402

env = os.environ.copy()
env["ENABLE_DEMO_ROUTES"] = "true"
env["ASR_PROVIDER"] = "mock"  # mock to save VRAM
env["OCR_PROVIDER"] = os.getenv("OCR_PROVIDER", "mock")

api_dir = str(Path(__file__).resolve().parents[1])

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8006"],
    cwd=api_dir, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
)

try:
    for i in range(30):
        try:
            r = requests.get("http://127.0.0.1:8006/healthz", timeout=2)
            if r.status_code == 200:
                print(f"Server ready after {i+1}s")
                break
        except requests.RequestException:
            time.sleep(1)
    else:
        print("Server failed")
        proc.kill()
        sys.exit(1)

    print("\n=== OCR Recognize ===")
    img = os.path.join(api_dir, "tests/test_ocr_image.png")
    with open(img, "rb") as f:
        r = requests.post("http://127.0.0.1:8006/api/v1/ocr/recognize",
                         files={"file": ("test.png", f, "image/png")},
                         timeout=600)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"Text:\n{data.get('text', 'N/A')}")
        print(f"Regions: {len(data.get('regions', []))}")
        print(f"Provider: {data.get('provider', 'N/A')}")
        print(f"Duration: {data.get('duration_ms', 'N/A')}ms")
    else:
        print(f"Error: {r.text[:500]}")

    assert r.status_code == 200, f"OCR failed: {r.status_code} {r.text[:500]}"

    print("\n=== OCR SMOKE TEST DONE ===")
finally:
    proc.terminate()
    proc.wait(timeout=5)
    print("Server stopped.")
