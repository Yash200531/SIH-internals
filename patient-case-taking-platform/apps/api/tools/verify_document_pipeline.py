"""Verify a synthetic prescription through the running local document pipeline."""

import argparse
import io
import json
import time
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw, ImageFont


def verify(base_url: str, font_path: str, timeout: int = 300) -> dict:
    if urlparse(base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Synthetic verifier requires a local API")
    image = Image.new("RGB", (1600, 520), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path, 64)
    for y, line in (
        (60, "PRESCRIPTION"),
        (190, "METFORMIN 500 MG"),
        (320, "TAKE ONE TABLET DAILY"),
    ):
        draw.text((70, y), line, fill="black", font=font)
    output = io.BytesIO()
    image.save(output, format="PNG")
    payload = output.getvalue()
    tenant, patient, facility, encounter = (str(uuid4()) for _ in range(4))
    with httpx.Client(base_url=base_url, timeout=30) as client:

        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        def identity(role, user):
            token = request(
                "POST",
                "/api/v1/auth/token",
                params={
                    "user_id": user,
                    "email": f"{role}@ocr-verification.example.test",
                    "role": role,
                    "tenant_id": tenant,
                    "facility_ids": facility,
                },
            )
            return {"Authorization": f"Bearer {token['token']}"}

        patient_headers = identity("patient", patient)
        doctor_headers = identity("doctor", str(uuid4()))
        portal = "/api/v1/patient-portal/me"
        consent = request(
            "POST",
            portal + "/consents",
            headers=patient_headers,
            json={"encounter_id": encounter, "document_upload": True},
        )
        document = request(
            "POST",
            portal + "/documents",
            headers={**patient_headers, "Idempotency-Key": str(uuid4())},
            json={
                "facility_id": facility,
                "encounter_id": encounter,
                "consent_reference": consent["id"],
                "original_filename": "synthetic-prescription.png",
                "declared_mime": "image/png",
                "declared_size_bytes": len(payload),
            },
        )
        document_id = document["id"]
        grant = request(
            "POST", f"{portal}/documents/{document_id}/upload-session", headers=patient_headers
        )
        # No bearer credentials are sent to object storage.
        uploaded = httpx.put(
            grant["url"], headers=grant["required_headers"], content=payload, timeout=30
        )
        uploaded.raise_for_status()
        request(
            "POST",
            f"{portal}/documents/{document_id}/finalize",
            headers=patient_headers,
            json={"expected_version": document["version"]},
        )
        deadline = time.monotonic() + timeout
        previous = None
        while time.monotonic() < deadline:
            documents = request("GET", portal + "/documents", headers=patient_headers)
            document = next(item for item in documents if item["id"] == document_id)
            state = document["state"]
            if state != previous:
                print(f"document={document_id} state={state}", flush=True)
                previous = state
            if state == "review_required":
                break
            if "failed" in state or state in {"rejected", "cancelled"}:
                raise RuntimeError(f"Pipeline failed: {state}")
            time.sleep(2)
        else:
            raise TimeoutError(f"Document {document_id} stalled in {previous}")
        path = f"/api/v1/document-reviews/{document_id}"
        review = request("GET", path, headers=doctor_headers)
        candidates = review["candidates"]
        expected = {("medication_statement", "METFORMIN"), ("strength", "500")}
        if {(item["entity_type"], item["normalized_value"]) for item in candidates} != expected:
            raise AssertionError("Candidates differ from the known synthetic prescription; do not auto-review")
        matching = [
            item for item in candidates if "metformin" in (item["normalized_value"] or "").lower()
        ]
        if not matching or not all(
            item["source_ocr_artifact_id"] and item["source_region_id"] for item in matching
        ):
            raise AssertionError("Real OCR must produce source-linked metformin candidates")
        timeline = request("GET", portal + "/timeline", headers=patient_headers)
        if any(item["document_id"] == document_id for item in timeline):
            raise AssertionError("Unreviewed OCR leaked into patient timeline")
        for item in candidates:
            request(
                "POST",
                f"{path}/candidates/{item['candidate_id']}/decisions",
                headers={**doctor_headers, "Idempotency-Key": str(uuid4())},
                json={
                    "action": "accept",
                    "expected_candidate_version": item["version"],
                    "source_verified": True,
                },
            )
        review = request("GET", path, headers=doctor_headers)
        finalized = request(
            "POST",
            path + "/finalize",
            headers={**doctor_headers, "Idempotency-Key": str(uuid4())},
            json={"expected_document_version": review["version"]},
        )
        deadline = time.monotonic() + timeout
        facts = []
        while time.monotonic() < deadline:
            timeline = request("GET", portal + "/timeline", headers=patient_headers)
            facts = [item for item in timeline if item["document_id"] == document_id]
            if len(facts) == len(candidates):
                break
            time.sleep(2)
        if not facts or not all(item["statement_status"] == "document_stated" for item in facts):
            raise AssertionError("Reviewed facts must retain document-stated semantics")
        return {
            "document_id": document_id,
            "state": finalized["state"],
            "candidates": len(candidates),
            "reviewed_facts": len(facts),
            "tenant_id": tenant,
            "patient_id": patient,
            "facility_id": facility,
            "encounter_id": encounter,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--font", default="C:/Windows/Fonts/arial.ttf")
    args = parser.parse_args()
    print(json.dumps(verify(args.api_url, args.font), indent=2))
