"""eval/compare_parsers.py: chọn trang, số đo từng trang (định tuyến + phần tử ⚠), bảng so sánh gộp với CER."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

from app.domain.models import PageFeatures, PageScores
from app.steps.parser import PageAnalysis
from tests.conftest import make_pdf

_spec = importlib.util.spec_from_file_location("compare_parsers", Path(__file__).parents[1] / "eval/compare_parsers.py")
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)


def test_parse_pages():
    assert cp.parse_pages("1,3,5-7,3", 10) == [1, 3, 5, 6, 7]
    assert cp.parse_pages("all", 3) == [1, 2, 3]
    with pytest.raises(ValueError):
        cp.parse_pages("9-12", 10)


def _fake(engine: str):
    def analyze(pdf, page, opts, parser):
        assert parser == engine
        easy = page == 1
        return PageAnalysis(
            engine,
            f"page {page} 1,200点\n",
            PageScores(low_score=0.95 if easy else 0.5, low_grade="excellent" if easy else "poor"),
            PageFeatures(n_tables=0 if easy else 1, complex_tables=0 if easy else 1),
            [
                {"label": "text", "bbox": [0, 0, 1, 0.1], "confidence": 0.99},
                {"label": "text", "bbox": [0, 0.2, 1, 0.3], "confidence": 0.7},  # ⚠ yếu
                {"label": "text", "bbox": [0, 0.4, 1, 0.5], "confidence": 0.4},  # ⚠ + AI đọc lại
                {"label": "picture", "bbox": [0, 0.6, 1, 0.7], "confidence": 0.1, "removed": True},  # logo: bỏ
            ],
        )

    return analyze


def test_run_then_report(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(make_pdf([["A"], ["B"], ["C"]]))
    items = [(f"page_{n:03d}", pdf, n) for n in (1, 2)]
    for engine in ("docling", "paddleocr"):
        rows = cp.run_engine(engine, items, tmp_path, allow_fallback=True, analyze=_fake(engine))
        assert [r["route"] for r in rows] == ["easy", "hard"]
        assert rows[1]["route_reasons"] == "low_grade;complex_table"
        assert (rows[0]["n_elements"], rows[0]["n_weak"], rows[0]["n_reread"]) == (3, 2, 1)
        assert (tmp_path / "ocr" / engine / "page_002.md").read_text(encoding="utf-8") == "page 2 1,200点\n"

    # per_page.csv như eval_cer.py ghi: paddleocr sai 1 số 点
    with open(tmp_path / "report" / "per_page.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["engine", "page", "chars_gt", "S_thay", "D_thieu", "I_thua", "CER", "so_diem_gt", "so_diem_sai"])
        w.writerow(["docling", "page_001", 100, 1, 0, 0, "1.00%", 2, 0])
        w.writerow(["paddleocr", "page_001", 100, 3, 1, 0, "4.00%", 2, 1])

    by = {r["engine"]: r for r in cp.summarize(tmp_path)}
    assert set(by) == {"docling", "paddleocr"}
    assert (by["docling"]["easy"], by["docling"]["hard"], by["docling"]["weak"]) == (1, 1, 4)
    assert by["docling"]["reasons"] == "low_grade=1 complex_table=1"
    assert (by["docling"]["cer"], by["docling"]["point_errors"]) == ("1.00%", 0)
    assert (by["paddleocr"]["cer"], by["paddleocr"]["point_errors"]) == ("4.00%", 1)
    assert cp.print_report(tmp_path) == 0
    assert (tmp_path / "report" / "compare.csv").exists()


def test_run_refuses_missing_engine(tmp_path, monkeypatch):
    import app.steps.parser as parser

    monkeypatch.setattr(parser, "parser_available", lambda kind: False)
    with pytest.raises(SystemExit, match="setup_parser.sh"):
        cp.run_engine("paddleocr", [], tmp_path)


def test_run_refuses_pdfium_fallback(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(make_pdf([["A"]]))

    def pdfium_only(data, page, opts, parser):
        return PageAnalysis("pdfium", "A\n", PageScores(), PageFeatures(), [])

    import app.steps.parser as parser

    orig = parser.parser_available
    parser.parser_available = lambda kind: True
    try:
        with pytest.raises(SystemExit, match="pdfium"):
            cp.run_engine("docling", [("page_001", pdf, 1)], tmp_path, analyze=pdfium_only)
    finally:
        parser.parser_available = orig


def test_manifest(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(make_pdf([["A"], ["B"]]))
    man = tmp_path / "manifest.csv"
    man.write_text("name,pdf,page\ntext_01,a.pdf,2\n", encoding="utf-8")
    args = cp.argparse.Namespace(manifest=str(man), pdf=None, pages="all")
    assert cp.items_from_args(args) == [("text_01", pdf, 2)]
    args = cp.argparse.Namespace(manifest=None, pdf=str(pdf), pages="all")
    assert [n for n, _, _ in cp.items_from_args(args)] == ["page_001", "page_002"]
