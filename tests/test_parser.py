"""Parser (標準解析): Docling + RapidOCR tiếng Nhật; thiếu thư viện thì fallback lớp text pdfium."""

from __future__ import annotations

import importlib.util

import pytest

from app.domain.models import Page
from app.domain.options import DoclingOptions, RoutingOptions
from app.steps import rules
from app.steps.parser import analyze_page, parser_available

HAS_DOCLING = importlib.util.find_spec("docling") is not None


@pytest.mark.skipif(HAS_DOCLING, reason="môi trường có Docling — fallback chỉ xảy ra khi thiếu thư viện")
def test_missing_parser_library_falls_back_to_pdfium(sample_pdf):
    assert not parser_available()
    a = analyze_page(sample_pdf, 1, DoclingOptions())
    assert a.engine == "pdfium"
    p = Page(id="0001", doc_id="d", page=1, book_page=1, engine=a.engine, scores=a.scores, features=a.features)
    route, reasons = rules.decide_route(p, RoutingOptions())
    assert route == "hard" and "no_docling" in reasons


def test_docling_ocr_defaults_to_rapidocr():
    """OCR mặc định trong Docling là RapidOCR (PP-OCRv6 tiếng Nhật).
    Benchmark sách scan: F1 ký tự 98,5 % so với 84,9 % của EasyOCR."""
    assert DoclingOptions().ocr_engine == "rapidocr"


def test_docling_ocr_options():
    pytest.importorskip("docling")
    from app.steps.docling_engine import ocr_options

    rapid = ocr_options("rapidocr", ("ja", "en"))
    assert type(rapid).__name__ == "RapidOcrOptions" and rapid.model_size == "small"
    assert len(rapid.lang) == 1 and rapid.lang[0].startswith("iso:ja")  # RapidOCR chạy một ngôn ngữ
    easy = ocr_options("easyocr", ("ja", "en"))
    assert type(easy).__name__ == "EasyOcrOptions" and easy.lang == ["ja", "en"]
    with pytest.raises(ValueError, match="ocr_engine"):
        ocr_options("tesseract", ("ja",))
