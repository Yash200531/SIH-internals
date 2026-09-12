"""Low-latency PP-OCRv5 provider for routine clinical document images."""

import asyncio
import importlib
import logging
import os
import tempfile
import threading
import time
from typing import Any

from app.config import settings
from app.ocr.base import OCRProvider, OCRRegion, OCRResult

logger = logging.getLogger(__name__)


def _result_payload(result) -> dict:
    """Return the stable result payload exposed by PaddleOCR 3.x."""
    json_value = getattr(result, "json", None)
    if isinstance(json_value, dict):
        payload = json_value.get("res", json_value)
        return payload if isinstance(payload, dict) else {}
    if isinstance(result, dict):
        return result.get("res", result)
    return {}


def _regions_from_payload(payload: dict) -> list[OCRRegion]:
    texts = payload.get("rec_texts") or []
    scores = payload.get("rec_scores") or []
    boxes = payload.get("rec_boxes") or []
    regions: list[OCRRegion] = []
    for index, raw_text in enumerate(texts):
        text = str(raw_text).strip()
        if not text:
            continue
        score = float(scores[index]) if index < len(scores) else None
        raw_box = boxes[index] if index < len(boxes) else None
        bbox = None
        if raw_box is not None and len(raw_box) == 4:
            bbox = (int(raw_box[0]), int(raw_box[1]), int(raw_box[2]), int(raw_box[3]))
        polygon = None
        if bbox is not None:
            x1, y1, x2, y2 = bbox
            polygon = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        regions.append(
            OCRRegion(
                text=text,
                confidence=score,
                bbox=bbox,
                polygon=polygon,
                reading_order=len(regions) + 1,
            )
        )
    return regions


class FastPaddleOCRProvider(OCRProvider):
    """PP-OCRv5 detector/recognizer with preprocessing stages disabled."""

    def __init__(self, language: str | None = None):
        self.language = language or settings.OCR_LANGUAGE
        self._pipeline: Any | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    @property
    def provider_name(self) -> str:
        return "paddleocr_fast"

    @property
    def model_version(self) -> str:
        return "PP-OCRv5-mobile"

    @property
    def language_pack_version(self) -> str:
        return "PP-OCRv5_mobile_rec"

    def _ensure_pipeline(self) -> None:
        if self._pipeline is not None:
            return
        with self._load_lock:
            if self._pipeline is not None:
                return
            if os.name == "nt":
                importlib.import_module("torch")
            from paddleocr import PaddleOCR

            self._pipeline = PaddleOCR(
                text_detection_model_name="PP-OCRv5_mobile_det",
                text_recognition_model_name="PP-OCRv5_mobile_rec",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                enable_mkldnn=settings.OCR_ENABLE_MKLDNN,
                device="cpu",
            )

    async def warmup(self) -> None:
        await asyncio.to_thread(self._ensure_pipeline)

    async def recognize(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
    ) -> OCRResult:
        if not image_bytes:
            raise ValueError("Image file is empty")
        started_at = time.monotonic()
        await asyncio.to_thread(self._ensure_pipeline)
        regions = await asyncio.to_thread(self._sync_recognize, image_bytes, mime_type)
        duration_ms = int((time.monotonic() - started_at) * 1000)
        scores = [region.confidence for region in regions if region.confidence is not None]
        return OCRResult(
            text="\n".join(region.text for region in regions),
            regions=regions,
            confidence=sum(scores) / len(scores) if scores else None,
            provider=self.provider_name,
            model_version=self.model_version,
            language_pack_version=self.language_pack_version,
            duration_ms=duration_ms,
        )

    def _sync_recognize(self, image_bytes: bytes, mime_type: str) -> list[OCRRegion]:
        suffix = {"image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime_type, ".png")
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            tmp.write(image_bytes)
            tmp.close()
            pipeline = self._pipeline
            if pipeline is None:
                raise RuntimeError("PaddleOCR pipeline is not initialized")
            with self._inference_lock:
                results = pipeline.predict(tmp.name)
                return [
                    region
                    for result in results
                    for region in _regions_from_payload(_result_payload(result))
                ]
        finally:
            os.unlink(tmp.name)
