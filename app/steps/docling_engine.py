"""Parser Docling: chạy cho một trang và rút ra markdown, điểm confidence, đặc trưng bảng/hình, toạ độ phần tử.

Chọn engine ở `app/steps/parser.py` (PARSER_TYPE). Docling chỉ có trong image worker parser (nặng).
"""

from __future__ import annotations

import io
import math
import os
import re
from functools import lru_cache

from app.domain.models import PageFeatures, PageScores
from app.domain.options import DoclingOptions
from app.steps.common import page_text_pdfium
from app.steps.parser import PageAnalysis


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else round(f, 4)


def _grade(v) -> str:
    return getattr(v, "value", str(v or "unspecified")).lower()


@lru_cache(maxsize=4)
def _converter(do_ocr: bool, langs: tuple[str, ...], table_mode: str, classify: bool, scale: float):
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    if os.environ.get("DOCLING_ARTIFACTS_PATH"):  # model tải sẵn lúc build image, chạy không cần mạng
        opts.artifacts_path = os.environ["DOCLING_ARTIFACTS_PATH"]
    opts.do_ocr = do_ocr
    opts.ocr_options = EasyOcrOptions(lang=list(langs))
    opts.do_table_structure = True
    opts.table_structure_options.mode = TableFormerMode.ACCURATE if table_mode == "accurate" else TableFormerMode.FAST
    opts.do_picture_classification = classify
    opts.generate_picture_images = classify
    opts.images_scale = scale
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def _picture_class(pic) -> str:
    meta = getattr(pic, "meta", None)
    cls = getattr(meta, "classification", None) if meta else None
    preds = getattr(cls, "predictions", None) if cls else None
    if preds:
        return str(preds[0].class_name).lower()
    for ann in getattr(pic, "annotations", []) or []:
        pc = getattr(ann, "predicted_classes", None)
        if pc:
            return str(pc[0].class_name).lower()
    return ""


def _bbox_tl(prov, page_w: float, page_h: float) -> list[float]:
    bb = prov.bbox.to_top_left_origin(page_height=page_h)
    return [round(bb.l / page_w, 4), round(bb.t / page_h, 4), round(bb.r / page_w, 4), round(bb.b / page_h, 4)]


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _norm_box(bb, pw: float, ph: float) -> list[float] | None:
    """BoundingBox của Docling (gốc trên-trái hoặc dưới-trái) → [x0,y0,x1,y1] 0..1 gốc trên-trái."""
    try:
        bb = bb.to_top_left_origin(page_height=ph)
        return [round(bb.l / pw, 4), round(bb.t / ph, 4), round(bb.r / pw, 4), round(bb.b / ph, 4)]
    except Exception:  # noqa: BLE001
        return None


OCR_CELL_KEEP = 0.99  # chỉ giữ ô OCR có confidence dưới mức này cho đỡ nặng docling.json


def page_confidences(res, page: int, pw: float, ph: float) -> tuple[list[tuple[str, list[float], float]], list[dict]]:
    """Confidence theo vùng mà bản xuất DoclingDocument không giữ: cụm layout (`predictions.layout.clusters`)
    và ô chữ OCR (`cells` có `from_ocr`). Phiên bản Docling khác API thì trả rỗng — chỉ mất phần tô màu."""
    try:
        pages = list(getattr(res, "pages", None) or [])
        pg = next((p for p in pages if getattr(p, "page_no", None) == page - 1), None)
        if pg is None and len(pages) == 1:
            pg = pages[0]
        if pg is None:
            return [], []
        clusters = []
        layout = getattr(getattr(pg, "predictions", None), "layout", None)
        for cl in getattr(layout, "clusters", None) or []:
            box, conf = _norm_box(cl.bbox, pw, ph), _num(getattr(cl, "confidence", None))
            if box and conf is not None:
                clusters.append((str(getattr(cl, "label", "")).split(".")[-1].lower(), box, conf))
        cells = []
        for cell in getattr(pg, "cells", None) or []:
            conf = _num(getattr(cell, "confidence", None))
            if not getattr(cell, "from_ocr", False) or conf is None or conf >= OCR_CELL_KEEP:
                continue
            rect = getattr(cell, "rect", None)
            raw = (
                rect.to_bounding_box()
                if rect is not None and hasattr(rect, "to_bounding_box")
                else getattr(cell, "bbox", None)
            )
            box = _norm_box(raw, pw, ph) if raw is not None else None
            if box:
                cells.append(
                    {"label": "ocr_text", "bbox": box, "confidence": conf, "text": str(getattr(cell, "text", ""))[:200]}
                )
        return clusters, cells
    except Exception:  # noqa: BLE001 — điểm phụ cho UI, không làm hỏng bước Docling
        return [], []


def attach_confidence(elements: list[dict], clusters: list[tuple[str, list[float], float]]) -> None:
    """Gắn confidence của cụm layout trùng nhiều nhất (IoU ≥ 0.5) vào từng phần tử."""
    for el in elements:
        best = max(((_iou(el["bbox"], box), conf) for _label, box, conf in clusters), default=(0.0, None))
        if best[0] >= 0.5 and best[1] is not None:
            el["confidence"] = best[1]


def analyze_with_docling(pdf: bytes, page: int, opts: DoclingOptions) -> PageAnalysis:
    from docling.datamodel.base_models import DocumentStream

    conv = _converter(
        opts.do_ocr, tuple(opts.ocr_lang), opts.table_mode, opts.picture_classification, opts.images_scale
    )
    res = conv.convert(DocumentStream(name="page.pdf", stream=io.BytesIO(pdf)), page_range=(page, page))
    doc = res.document
    conf = res.confidence.pages.get(page)
    scores = PageScores()
    if conf is not None:
        scores = PageScores(
            parse_score=_num(conf.parse_score),
            layout_score=_num(conf.layout_score),
            ocr_score=_num(conf.ocr_score),
            table_score=_num(conf.table_score),
            mean_score=_num(conf.mean_score),
            low_score=_num(conf.low_score),
            mean_grade=_grade(conf.mean_grade),
            low_grade=_grade(conf.low_grade),
        )
    size = doc.pages[page].size
    pw, ph = float(size.width), float(size.height)
    feats = PageFeatures(has_text_layer=len(page_text_pdfium(pdf, page).strip()) > 20)
    elements: list[dict] = []
    removed_set = {c.lower() for c in opts.remove_picture_classes}

    for t in doc.tables:
        prov = next((p for p in t.prov if p.page_no == page), None)
        if not prov:
            continue
        feats.n_tables += 1
        cells = getattr(t.data, "table_cells", []) or []
        if any((c.row_span or 1) > 1 or (c.col_span or 1) > 1 for c in cells):
            feats.complex_tables += 1
        bb = _bbox_tl(prov, pw, ph)
        feats.table_at_top |= bb[1] < 0.12
        feats.table_at_bottom |= bb[3] > 0.88
        elements.append({"label": "table", "bbox": bb})

    figure_idx = 0
    placeholders: list[str] = []
    for pic in doc.pictures:
        prov = next((p for p in pic.prov if p.page_no == page), None)
        if not prov:
            continue
        bb = _bbox_tl(prov, pw, ph)
        cls = _picture_class(pic)
        if cls in removed_set:
            feats.removed[cls] = feats.removed.get(cls, 0) + 1
            elements.append({"label": "picture", "class": cls, "bbox": bb, "removed": True})
            placeholders.append("")
            continue
        area = max(0.0, (bb[2] - bb[0]) * (bb[3] - bb[1]))
        feats.n_figures += 1
        feats.max_figure_area = round(max(feats.max_figure_area, area), 4)
        elements.append({"label": "picture", "class": cls, "bbox": bb, "figure": figure_idx, "area": round(area, 4)})
        placeholders.append(f"<!-- figure:{figure_idx} -->")
        figure_idx += 1

    for item, _level in doc.iterate_items(page_no=page):
        label = str(getattr(item, "label", "")).split(".")[-1].lower()
        if label in ("table", "picture"):
            continue
        prov = next((p for p in getattr(item, "prov", []) if p.page_no == page), None)
        if prov:
            elements.append({"label": label, "bbox": _bbox_tl(prov, pw, ph)})

    clusters, ocr_cells = page_confidences(res, page, pw, ph)
    attach_confidence(elements, clusters)
    elements.extend(ocr_cells)

    md = doc.export_to_markdown(page_no=page, image_placeholder="<!-- image -->")
    it = iter(placeholders)
    md = re.sub(r"<!-- image -->", lambda _m: next(it, ""), md)
    return PageAnalysis("docling", md.strip() + "\n", scores, feats, elements)
