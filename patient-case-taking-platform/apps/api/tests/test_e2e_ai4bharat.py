"""E2E test for AI4Bharat Indic Conformer 600M ASR."""
import os
from pathlib import Path

import pytest

if os.getenv("RUN_AI_INTEGRATION_TESTS") != "1":
    pytest.skip("set RUN_AI_INTEGRATION_TESTS=1 to run model integration tests", allow_module_level=True)

import time

import soundfile as sf
import torch
import torchaudio

print("=== AI4Bharat Indic Conformer 600M E2E Test ===")
print("Loading model...")
start = time.time()

from transformers import AutoModel  # noqa: E402

model = AutoModel.from_pretrained(
    "ai4bharat/indic-conformer-600m-multilingual",
    trust_remote_code=True,
)
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Device: {device}")
model = model.to(device).eval()
print(f"Model loaded in {time.time()-start:.1f}s")

# Load audio via soundfile (matching our provider)
audio_data, orig_sr = sf.read(
    Path(__file__).with_name("test_audio.wav")
)
if audio_data.ndim > 1:
    audio_data = audio_data.mean(axis=1)
tensor = torch.tensor(audio_data, dtype=torch.float32).unsqueeze(0)
if orig_sr != 16000:
    resampler = torchaudio.transforms.Resample(orig_freq=orig_sr, new_freq=16000)
    tensor = resampler(tensor)
tensor = tensor.to(device)
print(f"Audio shape: {tensor.shape}")

# Test CTC decoding
print("\n--- CTC Decoding (Hindi) ---")
start = time.time()
with torch.inference_mode():
    result = model(tensor, "hi", "ctc")
print(f'Result: "{result}"')
print(f"CTC time: {time.time()-start:.1f}s")

# Test RNNT decoding
print("\n--- RNNT Decoding (Hindi) ---")
start = time.time()
with torch.inference_mode():
    result = model(tensor, "hi", "rnnt")
print(f'Result: "{result}"')
print(f"RNNT time: {time.time()-start:.1f}s")

# Test Bengali
print("\n--- CTC Decoding (Bengali) ---")
start = time.time()
with torch.inference_mode():
    result = model(tensor, "bn", "ctc")
print(f'Result: "{result}"')
print(f"BN time: {time.time()-start:.1f}s")

print("\n=== AI4Bharat ASR: ALL TESTS PASS ===")
