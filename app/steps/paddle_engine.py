"""Parser PaddleOCR (PP-StructureV3): bố cục + bảng + OCR cho một trang → `PageAnalysis` cùng định dạng với Docling.

- Markdown dựng lại từ `parsing_res_list` theo thứ tự đọc: tiêu đề → `#` / `##`, bảng HTML → bảng Markdown (`|`),
  hình → `<!-- figure:N -->` (để bước 精密解析 / VLM thay bằng mô tả), header / footer / số trang bỏ khỏi Markdown
  (vẫn giữ làm phần tử `page_header` / `page_footer`).
- Confidence phần tử = 0.7·trung bình + 0.3·thấp nhất của điểm OCR các dòng nằm trong vùng (không có dòng nào thì
  lấy điểm bố cục). Điểm trang (thang 0..1 như Docling): `mean_score` = trung bình điểm OCR, `low_score` = phân vị
  5%, `layout_score` = trung bình điểm bố cục; `ocr_score` chỉ đặt khi trang không có lớp text (bản scan).
- Con dấu (`seal`) → lớp `stamp`, ảnh ở header / footer → `logo`: bỏ nếu nằm trong `remove_picture_classes`.

`analysis_from_paddle` là hàm thuần (test được không cần Paddle); `analyze_with_paddle` render trang rồi gọi model.
Chạy `python -m app.steps.paddle_engine warmup` để tải model trước (image Docker / .venv-parser).
"""

from __future__ import annotations

import os
import re
import sys
from functools import lru_cache
from html.parser import HTMLParser
from statistics import mean

from app.domain.models import PageFeatures, PageScores
from app.domain.options import DoclingOptions
from app.steps.common import page_text_pdfium
from app.steps.parser import PageAnalysis, grade

# nhãn PP-DocLayout → nhãn chung (cùng bộ với Docling, xem app/steps/elements.py DOCLING_LABELS)
LABELS = {
    "doc_title": "title",
    "paragraph_title": "section_header",
    "text": "text",
    "content": "document_index",
    "abstract": "text",
    "reference": "text",
    "reference_content": "text",
    "aside_text": "text",
    "algorithm": "text",
    "vision_footnote": "footnote",
    "footnote": "footnote",
    "list": "list_item",
    "table": "table",
    "image": "picture",
    "figure": "picture",
    "chart": "picture",
    "seal": "picture",
    "header_image": "picture",
    "footer_image": "picture",
    "figure_title": "caption",
    "table_title": "caption",
    "chart_title": "caption",
    "formula": "formula",
    "formula_number": "text",
    "header": "page_header",
    "footer": "page_footer",
    "number": "page_footer",
}
PICTURE_CLASS = {"seal": "stamp", "header_image": "logo", "footer_image": "logo", "chart": "chart"}
NOT_IN_MARKDOWN = {"header", "footer", "number", "header_image", "footer_image", "seal"}


# ================================================================== bảng HTML → Markdown
class _TableHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[tuple[str, int, int]]] = []
        self._cell: list[str] | None = None
        self._span = (1, 1)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            if not self.rows:
                self.rows.append([])
            self._cell = []
            self._span = (_int(a.get("rowspan")), _int(a.get("colspan")))
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self.rows[-1].append((text, *self._span))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _int(v) -> int:
    try:
        return max(1, int(v))
    except (TypeError, ValueError):
        return 1


def table_html_info(html: str) -> tuple[str, bool]:
    """(bảng Markdown, có ô gộp hay không). Ô gộp được lặp lại nội dung để mỗi hàng đủ cột."""
    p = _TableHTML()
    p.feed(html or "")
    grid: dict[tuple[int, int], str] = {}
    merged = False
    for r, row in enumerate(p.rows):
        c = 0
        for text, rs, cs in row:
            while (r, c) in grid:
                c += 1
            merged |= rs > 1 or cs > 1
            for dr in range(rs):
                for dc in range(cs):
                    grid[(r + dr, c + dc)] = text
            c += cs
    if not grid:
        return "", False
    n_rows = max(r for r, _ in grid) + 1
    n_cols = max(c for _, c in grid) + 1
    lines = []
    for r in range(n_rows):
        cells = [grid.get((r, c), "").replace("|", "\\|") for c in range(n_cols)]
        lines.append("| " + " | ".join(cells) + " |")
        if r == 0:
            lines.append("|" + "|".join(["---"] * n_cols) + "|")
    return "\n".join(lines), merged


# ================================================================== kết quả model → PageAnalysis
def _box(v, w: float, h: float) -> list[float] | None:
    try:
        x0, y0, x1, y1 = (float(x) for x in list(v)[:4])
    except (TypeError, ValueError):
        return None
    return [round(min(1.0, max(0.0, x)), 4) for x in (x0 / w, y0 / h, x1 / w, y1 / h)]


def _poly_box(pts) -> list[float] | None:
    try:
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
    except (TypeError, ValueError, IndexError):
        return None
    return [min(xs), min(ys), max(xs), max(ys)] if xs else None


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _center_in(b: list[float], box: list[float]) -> bool:
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def _pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(q * (len(s) - 1)))]


def _block_field(b: dict, *names: str):
    for n in names:
        if n in b:
            return b[n]
    return None


def analysis_from_paddle(
    res: dict, width: float, height: float, has_text_layer: bool, opts: DoclingOptions
) -> PageAnalysis:
    """`res` = `result.json["res"]` của PP-StructureV3 cho một ảnh trang (toạ độ theo pixel của ảnh đó)."""
    res = res.get("res", res) if isinstance(res, dict) else {}
    ocr = res.get("overall_ocr_res") or {}
    # rec_boxes = [x1,y1,x2,y2]; bản nào chỉ có rec_polys (4 điểm) thì lấy khung bao của đa giác
    boxes = ocr.get("rec_boxes")
    if boxes is None or len(boxes) == 0:
        boxes = [_poly_box(pts) for pts in ocr.get("rec_polys") or []]
    lines = []
    for text, score, box in zip(ocr.get("rec_texts") or [], ocr.get("rec_scores") or [], boxes, strict=False):
        bb = _box(box, width, height) if box is not None else None
        if bb is not None and score is not None:
            lines.append({"text": str(text), "score": float(score), "bbox": bb})
    layout = []
    for b in (res.get("layout_det_res") or {}).get("boxes") or []:
        bb = _box(b.get("coordinate") or [], width, height)
        if bb is not None:
            layout.append((str(b.get("label", "")), bb, float(b.get("score") or 0)))
    tables_html = [str(t.get("pred_html") or "") for t in res.get("table_res_list") or []]

    feats = PageFeatures(has_text_layer=has_text_layer)
    removed_set = {c.lower() for c in opts.remove_picture_classes}
    elements: list[dict] = []
    md_parts: list[str] = []
    figure_idx = 0
    table_idx = 0
    for blk in res.get("parsing_res_list") or []:
        raw_label = str(_block_field(blk, "block_label", "label") or "text").lower()
        bb = _box(_block_field(blk, "block_bbox", "bbox") or [], width, height)
        if bb is None:
            continue
        content = str(_block_field(blk, "block_content", "content") or "").strip()
        label = LABELS.get(raw_label, "text")
        inside = [ln["score"] for ln in lines if _center_in(ln["bbox"], bb)]
        lay = max(((_iou(bb, lb), sc) for lb_label, lb, sc in layout), default=(0.0, None))
        if inside:
            conf = round(0.7 * mean(inside) + 0.3 * min(inside), 4)
        else:
            conf = round(lay[1], 4) if lay[0] >= 0.5 and lay[1] is not None else None
        el: dict = {"label": label, "bbox": bb, "text": content, "paddle_label": raw_label}
        if conf is not None:
            el["confidence"] = conf

        if label == "picture":
            cls = PICTURE_CLASS.get(raw_label, "")
            el["class"] = cls
            if cls in removed_set:
                feats.removed[cls] = feats.removed.get(cls, 0) + 1
                el["removed"] = True
                elements.append(el)
                continue
            if raw_label in NOT_IN_MARKDOWN:
                elements.append(el)
                continue
            area = max(0.0, (bb[2] - bb[0]) * (bb[3] - bb[1]))
            feats.n_figures += 1
            feats.max_figure_area = round(max(feats.max_figure_area, area), 4)
            el.update(figure=figure_idx, area=round(area, 4), text="")
            md_parts.append(f"<!-- figure:{figure_idx} -->")
            figure_idx += 1
            elements.append(el)
            continue

        if label == "table":
            html = content
            if "<table" not in content.lower():  # bản cũ để HTML ở table_res_list theo thứ tự bảng
                html = tables_html[table_idx] if table_idx < len(tables_html) else ""
            table_idx += 1
            md, merged = table_html_info(html)
            feats.n_tables += 1
            feats.complex_tables += int(merged)
            feats.table_at_top |= bb[1] < 0.12
            feats.table_at_bottom |= bb[3] > 0.88
            el["text"] = md or content
            if md or content:
                md_parts.append(md or content)
            elements.append(el)
            continue

        elements.append(el)
        if raw_label in NOT_IN_MARKDOWN or not content:
            continue
        if label == "title":
            md_parts.append("# " + content.lstrip("# "))
        elif label == "section_header":
            md_parts.append("## " + content.lstrip("# "))
        else:
            md_parts.append(content)

    scores_all = [ln["score"] for ln in lines]
    layout_scores = [sc for _l, _b, sc in layout]
    mean_s = round(mean(scores_all), 4) if scores_all else None
    low_s = round(_pct(scores_all, 0.05), 4) if scores_all else None
    scores = PageScores(
        layout_score=round(mean(layout_scores), 4) if layout_scores else None,
        ocr_score=None if has_text_layer else mean_s,
        mean_score=mean_s,
        low_score=low_s,
        mean_grade=grade(mean_s),
        low_grade=grade(low_s),
    )
    md = "\n\n".join(p for p in md_parts if p.strip())
    return PageAnalysis("paddleocr", (md.strip() + "\n") if md.strip() else "", scores, feats, elements)


# ================================================================== chạy model
@lru_cache(maxsize=1)
def _pipeline():
    from paddleocr import PPStructureV3

    # Tắt phần không dùng (ảnh hướng giấy, nắn ảnh, công thức, biểu đồ, chữ trong con dấu) cho nhẹ và nhanh
    kw = {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_formula_recognition": False,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
    }
    if os.environ.get("PADDLE_DEVICE"):  # vd gpu:0 — mặc định Paddle tự chọn (CPU nếu không có GPU)
        kw["device"] = os.environ["PADDLE_DEVICE"]
    return PPStructureV3(**kw)


def _predict(img) -> dict:
    import numpy as np

    arr = np.array(img.convert("RGB"))[:, :, ::-1]  # PaddleX nhận ảnh BGR như OpenCV
    out = list(_pipeline().predict(arr))
    if not out:
        return {}
    j = out[0].json
    return j.get("res", j) if isinstance(j, dict) else {}


def analyze_with_paddle(pdf: bytes, page: int, opts: DoclingOptions) -> PageAnalysis:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    try:
        img = doc[page - 1].render(scale=opts.images_scale).to_pil()
    finally:
        doc.close()
    has_text = len(page_text_pdfium(pdf, page).strip()) > 20
    return analysis_from_paddle(_predict(img), img.width, img.height, has_text, opts)


def warmup() -> None:
    """Tải model và chạy thử một lần (dùng lúc build image / setup .venv-parser)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (800, 400), "white")
    ImageDraw.Draw(img).text((40, 40), "warmup 123", fill="black")
    _predict(img)
    print("paddleocr: models ready")


if __name__ == "__main__":
    if sys.argv[1:] == ["warmup"]:
        warmup()
    else:
        print("usage: python -m app.steps.paddle_engine warmup", file=sys.stderr)
        sys.exit(2)
