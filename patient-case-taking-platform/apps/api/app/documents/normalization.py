"""Bounded, metadata-stripping page normalization for scan-passed sources."""

import hashlib
import warnings
from dataclasses import dataclass
from io import BytesIO

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError

_IMAGE_FORMAT_BY_MIME = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


class DocumentNormalizationError(ValueError):
    """Raised with bounded detail when parser or admission controls reject a source."""


@dataclass(frozen=True)
class NormalizedPage:
    page_number: int
    width: int
    height: int
    mime: str
    data: bytes
    checksum_sha256: str
    preprocessing_version: str = "normalize.v1"
    operations: tuple[str, ...] = (
        "orientation_normalize",
        "metadata_strip",
        "lossless_png",
    )


class DocumentNormalizer:
    def __init__(
        self,
        *,
        max_pages: int,
        max_pixels_per_page: int,
        max_total_pixels: int | None = None,
        render_dpi: int = 200,
    ) -> None:
        self._max_pages = max_pages
        self._max_pixels_per_page = max_pixels_per_page
        self._max_total_pixels = max_total_pixels or max_pages * max_pixels_per_page
        self._render_dpi = render_dpi

    def _admit_dimensions(self, width: int, height: int, total_pixels: int) -> int:
        pixels = width * height
        if width <= 0 or height <= 0 or pixels > self._max_pixels_per_page:
            raise DocumentNormalizationError("Page exceeds pixel limit")
        total_pixels += pixels
        if total_pixels > self._max_total_pixels:
            raise DocumentNormalizationError("Document exceeds total pixel limit")
        return total_pixels

    @staticmethod
    def _to_safe_rgb(image: Image.Image) -> Image.Image:
        oriented = ImageOps.exif_transpose(image)
        if "A" in oriented.getbands():
            rgba = oriented.convert("RGBA")
            background = Image.new("RGBA", rgba.size, "white")
            normalized = Image.alpha_composite(background, rgba).convert("RGB")
        else:
            normalized = oriented.convert("RGB")
        normalized.info.clear()
        return normalized

    @staticmethod
    def _encode_page(image: Image.Image, page_number: int) -> NormalizedPage:
        output = BytesIO()
        image.save(output, format="PNG", optimize=False)
        data = output.getvalue()
        return NormalizedPage(
            page_number=page_number,
            width=image.width,
            height=image.height,
            mime="image/png",
            data=data,
            checksum_sha256=hashlib.sha256(data).hexdigest(),
        )

    def _normalize_image(self, payload: bytes, mime: str) -> list[NormalizedPage]:
        expected_format = _IMAGE_FORMAT_BY_MIME[mime]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(payload), formats=[expected_format]) as source:
                    if getattr(source, "n_frames", 1) != 1:
                        raise DocumentNormalizationError("Animated or multi-frame image rejected")
                    self._admit_dimensions(source.width, source.height, 0)
                    source.load()
                    normalized = self._to_safe_rgb(source)
        except DocumentNormalizationError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise DocumentNormalizationError("Image exceeds decompression limit") from exc
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise DocumentNormalizationError("Image parser rejected source") from exc
        return [self._encode_page(normalized, 1)]

    def _normalize_pdf(self, payload: bytes) -> list[NormalizedPage]:
        document = None
        try:
            document = pdfium.PdfDocument(payload)
            page_count = len(document)
            if page_count < 1 or page_count > self._max_pages:
                raise DocumentNormalizationError("PDF exceeds page limit")
            pages: list[NormalizedPage] = []
            total_pixels = 0
            scale = self._render_dpi / 72
            for index in range(page_count):
                page = document[index]
                bitmap = None
                try:
                    width_points, height_points = page.get_size()
                    width = max(1, round(width_points * scale))
                    height = max(1, round(height_points * scale))
                    total_pixels = self._admit_dimensions(width, height, total_pixels)
                    bitmap = page.render(scale=scale)
                    rendered = bitmap.to_pil().copy()
                    normalized = self._to_safe_rgb(rendered)
                    pages.append(self._encode_page(normalized, index + 1))
                finally:
                    if bitmap is not None:
                        bitmap.close()
                    page.close()
            return pages
        except DocumentNormalizationError:
            raise
        except Exception as exc:
            raise DocumentNormalizationError("PDF parser rejected source") from exc
        finally:
            if document is not None:
                document.close()

    def normalize(self, payload: bytes, mime: str) -> list[NormalizedPage]:
        if not payload:
            raise DocumentNormalizationError("Document source is empty")
        if mime == "application/pdf":
            return self._normalize_pdf(payload)
        if mime in _IMAGE_FORMAT_BY_MIME:
            return self._normalize_image(payload, mime)
        raise DocumentNormalizationError("Document type is not supported")
