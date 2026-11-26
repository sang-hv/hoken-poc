"""Parser (標準解析): Docling (OCR vùng ảnh / trang scan bằng RapidOCR tiếng Nhật — `DoclingOptions.ocr_engine`).

Trả `PageAnalysis`: Markdown của trang, điểm (PageScores, thang 0..1 của Docling), đặc trưng bảng / hình
(PageFeatures) và danh sách phần tử có bbox + confidence (+ `text`) cho định tuyến, tab 検査, nối trang và chunk.

Thư viện Docling chỉ có trong image worker parser hoặc `.venv-parser`. Thiếu thư viện thì dùng lớp text pdfium
(engine="pdfium") — trang đó bị định tuyến sang 精密解析 với lý do `no_docling` và có cảnh báo `parser.unavailable`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.models import PageFeatures, PageScores
from app.domain.options import DoclingOptions
from app.steps.common import page_text_pdfium

# engine của parser thật (khác fallback "pdfium")
PARSER_ENGINES = ("docling",)


@dataclass
class PageAnalysis:
    engine: str
    markdown: str
    scores: PageScores
    features: PageFeatures
    # {label, bbox[x0,y0,x1,y1] gốc trên-trái 0..1, confidence?, text?, removed?, figure?, area?}
    elements: list[dict] = field(default_factory=list)


def grade(score: float | None) -> str:
    """Bậc chất lượng theo thang của Docling: <0.5 poor, <0.8 fair, <0.9 good, ≥0.9 excellent."""
    if score is None:
        return "unspecified"
    return "poor" if score < 0.5 else "fair" if score < 0.8 else "good" if score < 0.9 else "excellent"


def parser_available() -> bool:
    try:
        import docling  # noqa: F401
    except ImportError:
        return False
    return True


def analyze_with_pdfium(pdf: bytes, page: int) -> PageAnalysis:
    from app.steps.rules import join_wrapped_lines

    text = page_text_pdfium(pdf, page)
    lines = [ln.rstrip() for ln in text.replace("\r", "").split("\n")]
    feats = PageFeatures(has_text_layer=len(text.strip()) > 20)
    md = join_wrapped_lines("\n".join(lines))
    return PageAnalysis("pdfium", md.strip() + "\n", PageScores(), feats, [])


def analyze_page(pdf: bytes, page: int, opts: DoclingOptions) -> PageAnalysis:
    if parser_available():
        from app.steps.docling_engine import analyze_with_docling

        return analyze_with_docling(pdf, page, opts)
    return analyze_with_pdfium(pdf, page)
