"""Bounded image/PDF page-normalization contract tests."""

from io import BytesIO

import pytest
from PIL import Image, PngImagePlugin

from app.documents.normalization import (
    DocumentNormalizationError,
    DocumentNormalizer,
)


def _image_bytes(
    *, width: int = 32, height: int = 24, format_name: str = "JPEG"
) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    output = BytesIO()
    image.save(output, format=format_name)
    return output.getvalue()


def test_image_normalization_is_lossless_png_and_strips_metadata() -> None:
    image = Image.new("RGB", (32, 24), "white")
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("patient_name", "must not survive")
    source = BytesIO()
    image.save(source, format="PNG", pnginfo=metadata)
    normalizer = DocumentNormalizer(max_pages=4, max_pixels_per_page=10_000)

    pages = normalizer.normalize(source.getvalue(), "image/png")

    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert pages[0].width == 32
    assert pages[0].height == 24
    assert pages[0].mime == "image/png"
    with Image.open(BytesIO(pages[0].data)) as normalized:
        assert normalized.info == {}
        assert normalized.format == "PNG"


def test_oversized_decompressed_image_is_rejected_before_derivative() -> None:
    normalizer = DocumentNormalizer(max_pages=1, max_pixels_per_page=10_000)

    with pytest.raises(DocumentNormalizationError, match="pixel limit"):
        normalizer.normalize(
            _image_bytes(width=101, height=101, format_name="PNG"),
            "image/png",
        )


def test_animated_webp_is_rejected() -> None:
    first = Image.new("RGB", (8, 8), "white")
    second = Image.new("RGB", (8, 8), "black")
    source = BytesIO()
    first.save(source, format="WEBP", save_all=True, append_images=[second])
    normalizer = DocumentNormalizer(max_pages=4, max_pixels_per_page=10_000)

    with pytest.raises(DocumentNormalizationError, match="multi-frame"):
        normalizer.normalize(source.getvalue(), "image/webp")


def test_pdf_page_limit_is_checked_before_rendering_all_pages() -> None:
    first = Image.new("RGB", (16, 16), "white")
    second = Image.new("RGB", (16, 16), "black")
    source = BytesIO()
    first.save(source, format="PDF", save_all=True, append_images=[second])
    normalizer = DocumentNormalizer(max_pages=1, max_pixels_per_page=100_000)

    with pytest.raises(DocumentNormalizationError, match="page limit"):
        normalizer.normalize(source.getvalue(), "application/pdf")


def test_two_page_pdf_produces_ordered_versioned_derivatives() -> None:
    first = Image.new("RGB", (16, 16), "white")
    second = Image.new("RGB", (16, 16), "black")
    source = BytesIO()
    first.save(source, format="PDF", save_all=True, append_images=[second])
    normalizer = DocumentNormalizer(
        max_pages=2,
        max_pixels_per_page=100_000,
        render_dpi=72,
    )

    pages = normalizer.normalize(source.getvalue(), "application/pdf")

    assert [page.page_number for page in pages] == [1, 2]
    assert all(page.preprocessing_version == "normalize.v1" for page in pages)
    assert all(page.checksum_sha256 for page in pages)
