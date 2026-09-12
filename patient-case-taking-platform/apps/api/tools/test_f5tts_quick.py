"""Quick F5-TTS smoke test — checks what loads and what takes long."""
import sys
import time

sys.path.insert(0, ".")
print("Importing f5_tts...")
t0 = time.monotonic()
from f5_tts.api import F5TTS  # noqa: E402 - measure this intentionally delayed import

print(f"Import done in {(time.monotonic()-t0)*1000:.0f}ms")
print()
print("Initialising F5TTS (downloads vocoder ~200MB if not cached)...")
t1 = time.monotonic()
tts = F5TTS(device="cuda")
print(f"Init done in {(time.monotonic()-t1)*1000:.0f}ms")
print(f"Device: {tts.device}")
print(f"Sample rate: {tts.target_sample_rate}")
print()
print("F5TTS base model ready.")
print("Now you can use tts.infer(ref_file, ref_text, gen_text)")
