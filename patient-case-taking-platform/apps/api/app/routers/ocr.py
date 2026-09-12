"""OCR endpoints for document/prescription processing."""
import base64
import binascii
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.ocr.registry import get_active_provider

router = APIRouter(prefix="/api/v1/ocr", tags=["ocr"])

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
logger = logging.getLogger(__name__)


@router.post("/recognize")
async def recognize_document(
    file: UploadFile = File(...),
):
    """OCR a document image (prescription, report, etc.).

    Accepts: PNG, JPEG, WebP images
    Returns: Extracted text with regions
    """
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported image type")

    image_bytes = await file.read(MAX_IMAGE_BYTES + 1)
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Image file is empty")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10MB)")

    try:
        result = await get_active_provider().recognize(image_bytes, file.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("OCR recognition failed")
        raise HTTPException(status_code=503, detail="OCR service unavailable") from exc

    return {
        "text": result.text,
        "regions": [
            {"text": r.text, "confidence": r.confidence, "bbox": r.bbox, "language": r.language}
            for r in result.regions
        ],
        "confidence": result.confidence,
        "provider": result.provider,
        "duration_ms": result.duration_ms,
    }


@router.post("/recognize-base64")
async def recognize_base64(
    image: str,  # base64 encoded
    mime_type: str = "image/png",
):
    """OCR from base64 image data."""
    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported image type")
    try:
        image_bytes = base64.b64decode(image, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 data") from exc
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Image data is empty")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10MB)")

    try:
        result = await get_active_provider().recognize(image_bytes, mime_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("OCR recognition failed")
        raise HTTPException(status_code=503, detail="OCR service unavailable") from exc

    return {
        "text": result.text,
        "regions": [
            {"text": r.text, "confidence": r.confidence, "bbox": r.bbox}
            for r in result.regions
        ],
        "confidence": result.confidence,
        "provider": result.provider,
        "duration_ms": result.duration_ms,
    }
