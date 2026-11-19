"""Chạy Docling cho một trang và rút ra: markdown, điểm confidence, đặc trưng bảng/hình, toạ độ phần tử.

Docling chỉ có trong image worker-docling (nặng). Nơi khác không cài Docling thì dùng pdfium để
trích text (engine="pdfium") — trang đó sẽ bị định tuyến sang CU với lý do `no_docling`.
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.domain.models import PageFeatures, PageScores
from app.domain.options import DoclingOptions
from app.steps.common import page_text_pdfium


@dataclass
class PageAnalysis:
    engine: str
    markdown: str
    scores: PageScores
    features: PageFeatures
    elements: list[dict] = field(default_factory=list)  # {label, bbox[x0,y0,x1,y1] top-left 0..1, removed, figure}


def docling_available() -> bool:
    try:
        import docling  # noqa: F401

        return True
    except ImportError:
        return False


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

    md = doc.export_to_markdown(page_no=page, image_placeholder="<!-- image -->")
    it = iter(placeholders)
    md = re.sub(r"<!-- image -->", lambda _m: next(it, ""), md)
    return PageAnalysis("docling", md.strip() + "\n", scores, feats, elements)


def analyze_with_pdfium(pdf: bytes, page: int) -> PageAnalysis:
    from app.steps.rules import join_wrapped_lines

    text = page_text_pdfium(pdf, page)
    lines = [ln.rstrip() for ln in text.replace("\r", "").split("\n")]
    feats = PageFeatures(has_text_layer=len(text.strip()) > 20)
    md = join_wrapped_lines("\n".join(lines))
    return PageAnalysis("pdfium", md.strip() + "\n", PageScores(), feats, [])


def analyze_page(pdf: bytes, page: int, opts: DoclingOptions) -> PageAnalysis:
    if docling_available():
        return analyze_with_docling(pdf, page, opts)
    return analyze_with_pdfium(pdf, page)
