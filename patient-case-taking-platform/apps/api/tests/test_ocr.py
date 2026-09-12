"""Tests for OCR provider."""
from types import SimpleNamespace

from app.ocr.base import OCRRegion, OCRResult
from app.ocr.fast_paddle_provider import (
    FastPaddleOCRProvider,
    _regions_from_payload,
    _result_payload,
)
from app.ocr.mock_provider import MockOCRProvider
from app.ocr.paddle_provider import _read_block


def test_ocr_region_dataclass():
    region = OCRRegion(
        text="hello",
        confidence=0.95,
        bbox=(0, 0, 100, 50),
        polygon=((0, 0), (100, 0), (100, 50), (0, 50)),
        script="Latn",
        reading_order=1,
    )
    assert region.text == "hello"
    assert region.bbox == (0, 0, 100, 50)
    assert region.polygon == ((0, 0), (100, 0), (100, 50), (0, 50))
    assert region.script == "Latn"
    assert region.reading_order == 1


def test_ocr_result_dataclass():
    result = OCRResult(
        text="prescription text",
        regions=[OCRRegion(text="line1", confidence=0.9)],
        confidence=0.9,
        provider="test",
        model_version="test-model-v1",
        language_pack_version="en-test-v1",
        duration_ms=100,
    )
    assert result.text == "prescription text"
    assert len(result.regions) == 1
    assert result.schema_version == "ocr-provider-result.v2"


def test_provider_versions_are_explicit_and_stable() -> None:
    mock = MockOCRProvider()
    paddle = FastPaddleOCRProvider(language="en")

    assert mock.model_version == "mock-ocr-v1"
    assert mock.language_pack_version == "synthetic-en-v1"
    assert paddle.model_version == "PP-OCRv5-mobile"
    assert paddle.language_pack_version == "PP-OCRv5_mobile_rec"


def test_paddleocr_37_object_block_is_normalized():
    block = SimpleNamespace(content="Patient Name: Ramesh Kumar", bbox=[1, 2, 3, 4])
    content, bbox = _read_block(block)
    assert content == "Patient Name: Ramesh Kumar"
    assert bbox == [1, 2, 3, 4]


def test_paddleocr_v5_result_payload_is_normalized():
    result = SimpleNamespace(
        json={
            "res": {
                "rec_texts": ["Patient Name: Ramesh Kumar", "Age: 45"],
                "rec_scores": [0.99, 0.97],
                "rec_boxes": [[10, 20, 300, 50], [10, 60, 100, 90]],
            }
        }
    )

    regions = _regions_from_payload(_result_payload(result))

    assert [region.text for region in regions] == ["Patient Name: Ramesh Kumar", "Age: 45"]
    assert regions[0].confidence == 0.99
    assert regions[0].bbox == (10, 20, 300, 50)
    assert regions[0].polygon == ((10, 20), (300, 20), (300, 50), (10, 50))
    assert regions[0].reading_order == 1


def test_paddleocr_v5_skips_blank_text_and_invalid_box():
    payload = {
        "rec_texts": ["", "Rx: Metformin 500mg"],
        "rec_scores": [0.1, 0.98],
        "rec_boxes": [[1, 2, 3, 4], [1, 2, 3]],
    }

    regions = _regions_from_payload(payload)

    assert len(regions) == 1
    assert regions[0].text == "Rx: Metformin 500mg"
    assert regions[0].bbox is None
