"""End-to-end ASR test on a real audio recording.

Usage:
    python -m tools.test_asr_recording "C:/Users/yashkumar/Desktop/Recording (31).wav" hi

This script:
1. Creates a demo patient token
2. Creates a patient session + consent
3. Sends the audio to /api/v1/asr/transcribe
4. Prints the transcription result
5. Feeds the transcript to MedGemma for a SOCRATES question
"""

import asyncio
import pathlib
import sys
import time

import httpx

BASE_URL = "http://localhost:8001"

# Fixed demo UUIDs — these are synthetic test identifiers
TENANT_ID   = "11111111-1111-4111-8111-111111111111"
PATIENT_ID  = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
FACILITY_ID = "22222222-2222-4222-8222-222222222222"
EMAIL       = "patient@test.local"


async def get_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        f"{BASE_URL}/api/v1/auth/token",
        params={
            "user_id": PATIENT_ID,
            "email": EMAIL,
            "role": "patient",
            "tenant_id": TENANT_ID,
            "facility_ids": FACILITY_ID,
        },
    )
    resp.raise_for_status()
    return resp.json()["token"]


async def create_session(client: httpx.AsyncClient, token: str) -> tuple[str, str]:
    import uuid
    resp = await client.post(
        f"{BASE_URL}/api/v1/patient-portal/me/sessions",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
        json={"facility_id": FACILITY_ID, "language": "hi"},
    )
    resp.raise_for_status()
    data = resp.json()
    return data["id"], data["encounter_id"]


async def create_consent(client: httpx.AsyncClient, token: str, encounter_id: str) -> str:
    import uuid
    resp = await client.post(
        f"{BASE_URL}/api/v1/patient-portal/me/consents",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
        json={"encounter_id": encounter_id},
    )
    resp.raise_for_status()
    return resp.json()["id"]


async def transcribe(
    client: httpx.AsyncClient,
    token: str,
    audio_path: str,
    language: str,
    session_id: str,
    encounter_id: str,
    consent_id: str,
) -> dict:
    path = pathlib.Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    ext = path.suffix.lower()
    mime = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
    }.get(ext, "audio/wav")

    print(f"  File     : {path.name}  ({path.stat().st_size // 1024} KB)  MIME: {mime}")

    audio_bytes = path.read_bytes()
    files = {"file": (path.name, audio_bytes, mime)}
    data = {
        "language": language,
        "tenant_id": TENANT_ID,
        "session_id": session_id,
        "encounter_id": encounter_id,
        "consent_id": consent_id,
    }

    t0 = time.monotonic()
    resp = await client.post(
        f"{BASE_URL}/api/v1/asr/transcribe",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
        data=data,
        timeout=300.0,  # 5 min — model download on first call
    )
    wall_ms = (time.monotonic() - t0) * 1000

    if resp.status_code != 200:
        print(f"  ERROR {resp.status_code}: {resp.text[:300]}")
        resp.raise_for_status()

    result = resp.json()
    result["_wall_ms"] = round(wall_ms)
    return result


async def ask_medgemma(transcript: str, language: str) -> None:
    """Feed the transcript to MedGemma for the next SOCRATES question."""
    import os
    import sys
    sys.path.insert(0, ".")
    os.environ.setdefault("LLM_PROVIDER", "medgemma")

    try:
        from app.llm.medgemma_provider import MedGemmaProvider
        provider = MedGemmaProvider()
        result = await provider.generate("dialogue.next_question", {
            "language": language,
            "chief_complaint": transcript,
            "last_patient_message": transcript,
            "collected_answers": {},
        })
        print()
        print("=== MEDGEMMA RESPONSE ===")
        print(f"Question     : {result.get('question')}")
        print(f"Domain       : {result.get('next_domain')}")
        print(f"Escalation   : {result.get('escalation_required')}")
        if result.get("safety_flags"):
            print(f"Safety flags : {result.get('safety_flags')}")
        print(f"Provider     : {result.get('provider')}")
    except Exception as e:
        print(f"MedGemma skipped: {e}")


async def main(audio_path: str, language: str = "hi") -> None:
    print()
    print("=" * 60)
    print("ASR END-TO-END TEST")
    print("=" * 60)
    print(f"Audio    : {audio_path}")
    print(f"Language : {language}")
    print(f"Server   : {BASE_URL}")
    print()

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Auth
        print("Step 1 — Getting demo token...")
        token = await get_token(client)
        print(f"  Token OK: {token[:20]}...")

        # Session
        print("Step 2 — Creating patient session...")
        session_id, encounter_id = await create_session(client, token)
        print(f"  Session ID   : {session_id}")
        print(f"  Encounter ID : {encounter_id}")

        # Consent
        print("Step 3 — Granting treatment consent...")
        consent_id = await create_consent(client, token, encounter_id)
        print(f"  Consent ID   : {consent_id}")

        # Transcribe
        print("Step 4 — Transcribing audio...")
        print("  (First call downloads AI4Bharat model ~2.4GB — may take 3-5 min)")
        result = await transcribe(
            client, token, audio_path, language,
            session_id, encounter_id, consent_id
        )

    print()
    print("=" * 60)
    print("TRANSCRIPTION RESULT")
    print("=" * 60)
    print(f"Text         : {result.get('text', '(empty)')}")
    print(f"Language     : {result.get('language')}")
    print(f"Provider     : {result.get('provider')}")
    print(f"Latency      : {result.get('processing_ms')} ms (model)")
    print(f"Wall time    : {result.get('_wall_ms')} ms (total)")
    confidence = result.get("confidence")
    if confidence is not None:
        print(f"Confidence   : {confidence:.2f}")
    print("=" * 60)

    # Feed to MedGemma
    transcript = result.get("text", "")
    if transcript.strip():
        print()
        print("Step 5 — Feeding transcript to MedGemma...")
        await ask_medgemma(transcript, language)
    else:
        print()
        print("No transcript text returned — skipping MedGemma step.")
        print("Check: is your recording audible? Try speaking clearly in Hindi or English.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m tools.test_asr_recording <audio_file> [language]")
        print("Example:")
        print('  python -m tools.test_asr_recording "C:/Users/yashkumar/Desktop/Recording (31).wav" hi')
        sys.exit(1)

    audio_file = sys.argv[1]
    lang = sys.argv[2] if len(sys.argv) > 2 else "hi"
    asyncio.run(main(audio_file, lang))
