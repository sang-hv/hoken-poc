"""Parser (標準解析): chọn engine theo PARSER_TYPE, kết quả PaddleOCR → PageAnalysis cùng định dạng Docling."""

from __future__ import annotations

import pytest

from app.core.settings import BootstrapSettings
from app.domain.models import Page
from app.domain.options import DoclingOptions, RoutingOptions
from app.steps import rules
from app.steps.paddle_engine import analysis_from_paddle, table_html_info
from app.steps.parser import analyze_page

W, H = 1000.0, 1400.0


def _res():
    """Kết quả PP-StructureV3 rút gọn (toạ độ pixel trên ảnh W×H)."""
    return {
        "parsing_res_list": [
            {"block_label": "header", "block_content": "歯科診療報酬点数表", "block_bbox": [100, 20, 600, 60]},
            {"block_label": "paragraph_title", "block_content": "M015-2 CAD/CAM冠", "block_bbox": [100, 100, 600, 140]},
            {"block_label": "text", "block_content": "1歯につき 1,200点", "block_bbox": [100, 160, 900, 220]},
            {
                "block_label": "table",
                "block_content": "<html><body><table><tr><td rowspan='2'>区分</td><td>点数</td></tr>"
                "<tr><td>1,200点</td></tr></table></body></html>",
                "block_bbox": [100, 1300, 900, 1390],
            },
            {"block_label": "image", "block_content": "", "block_bbox": [100, 400, 900, 900]},
            {"block_label": "seal", "block_content": "", "block_bbox": [800, 1000, 900, 1100]},
            {"block_label": "number", "block_content": "537", "block_bbox": [480, 1395, 520, 1400]},
        ],
        "layout_det_res": {
            "boxes": [
                {"label": "paragraph_title", "score": 0.95, "coordinate": [100, 100, 600, 140]},
                {"label": "image", "score": 0.6, "coordinate": [100, 400, 900, 900]},
            ]
        },
        "overall_ocr_res": {
            "rec_texts": ["M015-2 CAD/CAM冠", "1歯につき", "1,200点"],
            "rec_scores": [0.99, 0.9, 0.5],
            "rec_boxes": [[100, 100, 600, 140], [100, 160, 400, 220], [500, 160, 900, 220]],
        },
    }


def test_paddle_result_maps_to_page_analysis():
    a = analysis_from_paddle(_res(), W, H, has_text_layer=True, opts=DoclingOptions())
    assert a.engine == "paddleocr"
    # Markdown: tiêu đề mục, đoạn văn, hình → placeholder, bảng HTML → bảng Markdown; header / số trang / con dấu bỏ
    assert a.markdown.splitlines()[0] == "## M015-2 CAD/CAM冠"
    assert "<!-- figure:0 -->" in a.markdown and "| 区分 | 点数 |" in a.markdown and "| 区分 | 1,200点 |" in a.markdown
    assert "歯科診療報酬点数表" not in a.markdown and "537" not in a.markdown
    f = a.features
    assert (f.n_tables, f.complex_tables, f.table_at_bottom, f.n_figures, f.removed) == (1, 1, True, 1, {"stamp": 1})
    assert f.max_figure_area == pytest.approx(0.8 * 500 / 1400, abs=1e-3)
    by = {e["paddle_label"]: e for e in a.elements}
    assert by["text"]["confidence"] == pytest.approx(0.7 * 0.7 + 0.3 * 0.5)  # điểm OCR các dòng trong vùng
    assert by["image"]["confidence"] == 0.6  # không có dòng chữ → điểm bố cục
    assert by["seal"]["removed"] and by["header"]["label"] == "page_header"
    s = a.scores
    assert s.mean_score == pytest.approx(0.7967, abs=1e-3) and s.low_score == 0.5 and s.low_grade == "fair"
    assert s.ocr_score is None  # có lớp text → không phải trang OCR


def test_paddle_scanned_page_sets_ocr_score_and_routes_hard():
    a = analysis_from_paddle(_res(), W, H, has_text_layer=False, opts=DoclingOptions())
    assert a.scores.ocr_score is not None
    p = Page(id="0001", doc_id="d", page=1, book_page=1, engine=a.engine, scores=a.scores, features=a.features)
    route, reasons = rules.decide_route(p, RoutingOptions())
    assert route == "hard" and "no_docling" not in reasons and {"low_grade", "ocr", "scanned"} <= set(reasons)


def test_paddle_ocr_boxes_from_polygons():
    """Bản chỉ có rec_polys (không rec_boxes) vẫn tính được confidence theo dòng."""
    res = _res()
    ocr = res["overall_ocr_res"]
    ocr["rec_polys"] = [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]] for x0, y0, x1, y1 in ocr.pop("rec_boxes")]
    a = analysis_from_paddle(res, W, H, has_text_layer=True, opts=DoclingOptions())
    by = {e["paddle_label"]: e for e in a.elements}
    assert by["text"]["confidence"] == pytest.approx(0.7 * 0.7 + 0.3 * 0.5)


def test_table_html_expands_spans():
    md, merged = table_html_info("<table><tr><th colspan=2>A|B</th></tr><tr><td>1</td><td>2</td></tr></table>")
    assert merged and md.splitlines() == ["| A\\|B | A\\|B |", "|---|---|", "| 1 | 2 |"]
    assert table_html_info("") == ("", False)


def test_parser_type_validated():
    BootstrapSettings(jwt_secret="x" * 32, parser_type="paddleocr").validate()
    with pytest.raises(RuntimeError, match="PARSER_TYPE"):
        BootstrapSettings(jwt_secret="x" * 32, parser_type="tesseract").validate()


def test_missing_parser_library_falls_back_to_pdfium(sample_pdf):
    for kind in ("docling", "paddleocr"):
        assert analyze_page(sample_pdf, 1, DoclingOptions(), parser=kind).engine == "pdfium"
