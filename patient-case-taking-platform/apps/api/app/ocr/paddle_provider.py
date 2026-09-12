"""PaddleOCR-VL provider for document/prescription OCR.

Model: PaddlePaddle/PaddleOCR-VL (0.9B VLM)
Supports: text, tables, formulas, charts, 109 languages
Architecture: NaViT visual encoder + ERNIE-4.5-0.3B language model

Uses native paddleocr library (not transformers) to avoid version conflicts.
"""
import asyncio
import importlib
import logging
import os
import tempfile
import threading
import time
from typing import Any

from app.ocr.base import OCRProvider, OCRRegion, OCRResult

logger = logging.getLogger(__name__)


def _read_block(block) -> tuple[str, list[int] | tuple[int, ...] | None]:
    """Normalize PaddleOCR 3.6 dictionary blocks and 3.7 block objects."""
    if isinstance(block, dict):
        return str(block.get("block_content", "")).strip(), block.get("block_bbox")
    content = getattr(block, "content", getattr(block, "block_content", ""))
    bbox = getattr(block, "bbox", getattr(block, "block_bbox", None))
    return str(content).strip(), bbox


class PaddleOCRProvider(OCRProvider):
    """PaddleOCR-VL provider using native paddleocr library.

    Uses lazy loading — pipeline loads on first OCR request.
    """

    def __init__(self):
        self._pipeline: Any | None = None
        self._load_lock = threading.Lock()

    @property
    def provider_name(self) -> str:
        return "paddleocr_vl"

    @property
    def model_version(self) -> str:
        return "PaddleOCR-VL-v1"

    @property
    def language_pack_version(self) -> str:
        return "paddleocr-multilingual-109"

    def _ensure_pipeline(self):
        """Lazy-load PaddleOCRVL pipeline on first use."""
        if self._pipeline is not None:
            return
        with self._load_lock:
            if self._pipeline is not None:
                return
            try:
                logger.info("Loading PaddleOCR-VL pipeline...")
                # On Windows, load PyTorch's DLLs before Paddle/ModelScope. The
                # reverse order can make torch/lib/shm.dll fail with WinError 127.
                if os.name == "nt":
                    importlib.import_module("torch")
                from paddleocr import PaddleOCRVL

                self._pipeline = PaddleOCRVL(pipeline_version="v1")
                logger.info("PaddleOCR-VL pipeline loaded")
            except Exception:
                logger.exception("Failed to load PaddleOCR-VL")
                raise

    async def warmup(self) -> None:
        await asyncio.to_thread(self._ensure_pipeline)

    async def recognize(self, image_bytes: bytes, mime_type: str = "image/png") -> OCRResult:
        """Recognize text in an image using PaddleOCR-VL."""
        if not image_bytes:
            raise ValueError("Image file is empty")
        start_time = time.time()
        await asyncio.to_thread(self._ensure_pipeline)
        text, regions = await asyncio.to_thread(self._sync_recognize, image_bytes)

        duration_ms = int((time.time() - start_time) * 1000)
        scores = [r.confidence for r in regions if r.confidence is not None]
        avg_conf = sum(scores) / len(scores) if scores else None

        return OCRResult(
            text=text,
            regions=regions,
            confidence=avg_conf,
            provider="paddleocr_vl",
            model_version=self.model_version,
            language_pack_version=self.language_pack_version,
            duration_ms=duration_ms,
        )

    def _sync_recognize(self, image_bytes: bytes) -> tuple[str, list[OCRRegion]]:
        """Synchronous OCR (runs in thread)."""
        # Save bytes to temp file (PaddleOCRVL expects file path)
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        try:
            tmp.write(image_bytes)
            tmp.close()

            pipeline = self._pipeline
            if pipeline is None:
                raise RuntimeError("PaddleOCR-VL pipeline is not initialized")
            output = pipeline.predict(tmp.name)
            text_parts: list[str] = []
            regions: list[OCRRegion] = []

            for result in output:
                res = result.get("res", result) if isinstance(result, dict) else result

                # PaddleOCR-VL returns parsing_res_list with block_content
                if isinstance(res, dict) and "parsing_res_list" in res:
                    for block in res["parsing_res_list"]:
                        content, bbox = _read_block(block)
                        if content:
                            text_parts.append(content)
                            normalized_bbox = None
                            if bbox is not None and len(bbox) == 4:
                                normalized_bbox = (
                                    int(bbox[0]),
                                    int(bbox[1]),
                                    int(bbox[2]),
                                    int(bbox[3]),
                                )
                            polygon = None
                            if normalized_bbox is not None:
                                x1, y1, x2, y2 = normalized_bbox
                                polygon = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
                            regions.append(
                                OCRRegion(
                                    text=content,
                                    confidence=None,
                                    bbox=normalized_bbox,
                                    language=None,
                                    polygon=polygon,
                                    reading_order=len(regions) + 1,
                                )
                            )
                elif hasattr(res, "rec_texts") and res.rec_texts:
                    for i, txt in enumerate(res.rec_texts):
                        text_parts.append(txt)
                        conf = res.rec_scores[i] if hasattr(res, "rec_scores") and i < len(res.rec_scores) else None
                        regions.append(
                            OCRRegion(
                                text=txt,
                                confidence=float(conf) if conf is not None else None,
                                reading_order=len(regions) + 1,
                            )
                        )

            full_text = "\n".join(text_parts) if text_parts else ""
            return full_text, regions
        finally:
            os.unlink(tmp.name)
