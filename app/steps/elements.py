"""UI v2 (tab 検査) — dựng phần tử theo thứ tự đọc cho một trang từ kết quả sẵn có.

Nguồn (ưu tiên theo thứ tự):
  1. Content Understanding (`cu.json`): paragraphs / tables / figures có role + polygon `source`; không có paragraphs
     (vd mock) thì gom `words` thành dòng → khối. Confidence = 0.7·trung bình + 0.3·thấp nhất của các từ trong vùng.
  2. Docling (`docling.json`, engine "docling"): phần tử có label + bbox + confidence; chữ thô lấy từ `text` nếu có,
     không thì từ lớp text pdfium nằm trong bbox. Ô OCR (`ocr_text`) chỉ dùng để hạ confidence.
  3. pdfium (fallback): gom ký tự của lớp text thành dòng → khối, gán nhãn theo heuristic (mục lục có dấu dẫn,
     mã mục / chữ lớn → tiêu đề, dòng nhiều cột → bảng, ・/(1) → danh sách, 注/※ cuối trang → chú thích…).

Sau đó: sắp theo thứ tự đọc (trên → dưới, trái → phải trong một hàng) và gán Markdown hiện tại của trang cho từng
phần tử bằng cách so nội dung (bigram ký tự) từng khối Markdown với chữ thô của phần tử. Mỗi khối Markdown thuộc đúng
một phần tử nên ghép lại (`rebuild_markdown`) sẽ ra lại Markdown của trang.

Mọi hàm ở đây thuần (không đọc/ghi blob) trừ `pdfium_tokens` (đọc lớp text từ bytes PDF).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from app.steps.rules import HEADER_FOOTER, norm_text, parse_cu_source

LABELS = (
    "title",
    "section_header",
    "text",
    "list",
    "toc",
    "table",
    "picture",
    "caption",
    "formula",
    "footnote",
    "page_header",
    "page_footer",
)

DOCLING_LABELS = {
    "title": "title",
    "section_header": "section_header",
    "text": "text",
    "paragraph": "text",
    "list_item": "list",
    "document_index": "toc",
    "table": "table",
    "picture": "picture",
    "chart": "picture",
    "caption": "caption",
    "formula": "formula",
    "footnote": "footnote",
    "page_header": "page_header",
    "page_footer": "page_footer",
}

CU_ROLES = {
    "title": "title",
    "sectionHeading": "section_header",
    "pageHeader": "page_header",
    "pageFooter": "page_footer",
    "pageNumber": "page_footer",
    "footnote": "footnote",
    "formulaBlock": "formula",
}

_ITEM_CODE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:区分番号\s*)?[「\[【（(]?\s*[A-Z]\d{3}(?:-\d+){0,3}(?![\d-])")
_TOC = re.compile(r"(\.{3,}|…{2,}|・{3,}|･{3,}|‥{2,}|·{3,})\s*[0-9０-９]{1,4}\s*$")
_LIST = re.compile(
    r"^([・•●○◦▪■□◆◇]|[-－*]\s|\(?[0-9０-９]{1,2}[).）]|[（(][0-9０-９]{1,2}[)）]|[①-⑳]|[ア-ン][.．）)])"
)
_NOTE = re.compile(r"^(注|※|\*\d)")
_CAPTION = re.compile(r"^(図|表|Figure|Fig\.|Table)\s*[0-9０-９]+")
_PAGE_NO = re.compile(r"^[\s\-－—–‐(（]*[0-9０-９]{1,4}[\s\-－—–‐)）]*$")
_FIGURE = re.compile(r"^<!--\s*figure:(\d+)\s*-->$")
_ASCII = re.compile(r"[ -~]")


# ================================================================== token / dòng
@dataclass
class Tok:
    text: str
    bbox: list[float]  # x0,y0,x1,y1 gốc trên-trái 0..1
    conf: float | None = None

    @property
    def h(self) -> float:
        return max(1e-4, self.bbox[3] - self.bbox[1])

    @property
    def yc(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2


@dataclass
class TextLine:
    toks: list[Tok] = field(default_factory=list)
    cells: list[str] = field(default_factory=list)

    @property
    def bbox(self) -> list[float]:
        return union([t.bbox for t in self.toks])

    @property
    def text(self) -> str:
        return " ".join(self.cells).strip()

    @property
    def h(self) -> float:
        b = self.bbox
        return max(1e-4, b[3] - b[1])


def union(boxes: list[list[float]]) -> list[float]:
    if not boxes:
        return [0.0, 0.0, 1.0, 1.0]
    return [
        round(min(b[0] for b in boxes), 4),
        round(min(b[1] for b in boxes), 4),
        round(max(b[2] for b in boxes), 4),
        round(max(b[3] for b in boxes), 4),
    ]


def _center_in(inner: list[float], outer: list[float], pad: float = 0.005) -> bool:
    cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] - pad <= cx <= outer[2] + pad and outer[1] - pad <= cy <= outer[3] + pad


def iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def pdfium_tokens(pdf: bytes, page: int) -> list[Tok]:
    """Lớp text của trang → đoạn chữ liền nhau trên một dòng (tách ở xuống dòng hoặc khoảng trống lớn)."""
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(pdf)
        pg = doc[page - 1]
        w, h = pg.get_size()
        tp = pg.get_textpage()
        n = tp.count_chars()
    except Exception:  # noqa: BLE001 — PDF hỏng / không có lớp text → không có token
        return []
    toks: list[Tok] = []
    cur_text, cur_boxes, last = "", [], None

    def flush():
        nonlocal cur_text, cur_boxes
        if cur_text.strip() and cur_boxes:
            toks.append(Tok(cur_text.strip(), union(cur_boxes)))
        cur_text, cur_boxes = "", []

    for i in range(n):
        ch = tp.get_text_range(i, 1)
        if ch in ("\r", "\n"):
            flush()
            last = None
            continue
        left, bottom, right, top = tp.get_charbox(i)
        if ch.isspace():
            if cur_text:
                cur_text += " "
            continue
        box = [left / w, 1 - top / h, right / w, 1 - bottom / h]
        box = [round(min(1.0, max(0.0, v)), 4) for v in box]
        if last is not None:
            ch_h = max(1e-4, box[3] - box[1], last[3] - last[1])
            if box[0] - last[2] > 1.5 * ch_h or abs((box[1] + box[3]) / 2 - (last[1] + last[3]) / 2) > ch_h:
                flush()
        cur_text += ch
        cur_boxes.append(box)
        last = box
    flush()
    return toks


def group_lines(toks: list[Tok]) -> list[TextLine]:
    """Token cùng hàng (lệch tâm dọc < nửa chiều cao) → một dòng; khoảng trống > 1.5× chiều cao chữ = ranh giới ô."""
    lines: list[TextLine] = []
    for t in sorted(toks, key=lambda t: (t.yc, t.bbox[0])):
        for ln in reversed(lines[-3:]):
            lb = ln.bbox
            lyc = (lb[1] + lb[3]) / 2
            if abs(t.yc - lyc) < 0.5 * max(t.h, ln.h) and abs(t.yc - lyc) < 0.5 * max(ln.h, 0.004):
                ln.toks.append(t)
                break
        else:
            lines.append(TextLine([t]))
    for ln in lines:
        ln.toks.sort(key=lambda t: t.bbox[0])
        cells: list[str] = []
        prev: Tok | None = None
        for t in ln.toks:
            if prev is None:
                cells.append(t.text)
            else:
                gap = t.bbox[0] - prev.bbox[2]
                hh = max(t.h, prev.h)
                if gap > 1.5 * hh:
                    cells.append(t.text)
                else:
                    ascii_pair = bool(_ASCII.match(prev.text[-1:])) and bool(_ASCII.match(t.text[:1]))
                    cells[-1] += (" " if ascii_pair and gap > 0.1 * hh else "") + t.text
            prev = t
        ln.cells = cells
    lines.sort(key=lambda ln: (ln.bbox[1], ln.bbox[0]))
    return lines


# ================================================================== nhãn theo heuristic
def text_label(text: str) -> str:
    """Nhãn cho khối chữ thường theo nội dung (dùng cho Docling 'text', CU không có role)."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return "text"
    if sum(1 for ln in lines if _TOC.search(ln)) >= max(1, len(lines) // 2 + (len(lines) > 1)):
        return "toc"
    if _CAPTION.match(lines[0]) and len(lines[0]) <= 60:
        return "caption"
    if _LIST.match(lines[0]):
        return "list"
    return "text"


def line_label(ln: TextLine, median_h: float, has_title: bool) -> str:
    t = ln.text
    b = ln.bbox
    yc = (b[1] + b[3]) / 2
    if _PAGE_NO.match(t):
        return "page_header" if yc < 0.5 else "page_footer"
    if len(t) <= 60 and yc < 0.06:
        return "page_header"
    if len(t) <= 60 and yc > 0.95:
        return "page_footer"
    if _TOC.search(t):
        return "toc"
    if "|" in t and t.count("|") >= 2 or len(ln.cells) >= 3:
        return "table"
    if len(ln.cells) == 2 and len(t) <= 40 and re.search(r"[0-9０-９]", ln.cells[-1]):
        return "table"
    if _ITEM_CODE.match(t) and len(t) <= 50:
        return "section_header"
    if not has_title and ln.h >= 1.8 * median_h and yc < 0.3 and len(t) <= 60:
        return "title"
    if ln.h >= 1.5 * median_h and len(t) <= 40:
        return "section_header"
    if _CAPTION.match(t) and len(t) <= 60:
        return "caption"
    if _NOTE.match(t) and yc > 0.75:
        return "footnote"
    if _LIST.match(t):
        return "list"
    return "text"


SINGLE_LINE = ("title", "section_header", "caption", "page_header", "page_footer")
ROW_LABELS = ("table", "toc", "list")


def blocks_from_lines(lines: list[TextLine], source: str) -> list[dict]:
    """Dòng → khối: dòng liền nhau (khoảng cách ≤ 1× chiều cao chữ, cùng lề trái) và cùng loại thì gộp."""
    if not lines:
        return []
    med = median(ln.h for ln in lines if len(ln.text) >= 4) if any(len(ln.text) >= 4 for ln in lines) else 0.01
    blocks: list[dict] = []
    has_title = False
    cur: dict | None = None
    prev_ln: TextLine | None = None
    for ln in lines:
        label = line_label(ln, med, has_title)
        if label == "title":
            has_title = True
        if cur is not None and prev_ln is not None:
            pb, b = prev_ln.bbox, ln.bbox
            gap = b[1] - pb[3]
            close = gap <= (2.0 if label in ROW_LABELS else 1.0) * med and abs(b[0] - cur["_x0"]) <= 0.15
            same = label == cur["label"] or (cur["label"] == "list" and label == "text" and b[0] > cur["_x0"] + 0.005)
            if close and same and label not in SINGLE_LINE:
                cur["_lines"].append(ln)
                prev_ln = ln
                continue
        if (
            label == "table"
            and cur is not None
            and cur["label"] == "text"
            and len(cur["_lines"]) == 1
            and len(cur["_lines"][0].cells) >= 2
            and prev_ln is not None
            and ln.bbox[1] - prev_ln.bbox[3] <= 2.0 * med
        ):
            cur["label"] = "table"  # hàng tiêu đề bảng (không có số) đứng ngay trên các hàng bảng
            cur["_lines"].append(ln)
            cur["_x0"] = min(cur["_x0"], ln.bbox[0])
            prev_ln = ln
            continue
        cur = {"label": label, "_lines": [ln], "_x0": ln.bbox[0]}
        blocks.append(cur)
        prev_ln = ln
    out = []
    for b in blocks:
        toks = [t for ln in b["_lines"] for t in ln.toks]
        rows = [ln.text for ln in b["_lines"]]
        raw_text = "\n".join(" | ".join(ln.cells) if b["label"] == "table" else ln.text for ln in b["_lines"])
        out.append(
            {
                "label": b["label"],
                "bbox": union([t.bbox for t in toks]),
                "raw_text": raw_text,
                "confidence": token_confidence(toks),
                "source": source,
                "raw": {"engine": source, "lines": rows[:200]},
            }
        )
    return out


def token_confidence(toks: list[Tok]) -> float | None:
    confs = [t.conf for t in toks if t.conf is not None]
    if not confs:
        return None
    return round(0.7 * (sum(confs) / len(confs)) + 0.3 * min(confs), 3)


def _toks_text(toks: list[Tok]) -> str:
    return "\n".join(ln.text for ln in group_lines(toks))


# ================================================================== theo nguồn
def from_pdfium(toks: list[Tok]) -> list[dict]:
    return blocks_from_lines(group_lines(toks), "pdfium")


def from_docling(meta: dict, toks: list[Tok], complex_tables: int = 0) -> list[dict]:
    raw_els = [e for e in (meta or {}).get("elements") or [] if isinstance(e, dict) and e.get("bbox")]
    ocr = [e for e in raw_els if e.get("label") == "ocr_text"]
    out = []
    for el in raw_els:
        if el.get("removed") or el.get("label") == "ocr_text":
            continue
        bbox = [round(float(v), 4) for v in el["bbox"]]
        label = DOCLING_LABELS.get(str(el.get("label", "text")), "text")
        raw_text = el.get("text")
        if raw_text is None:
            raw_text = _toks_text([t for t in toks if _center_in(t.bbox, bbox)])
        if label == "text":
            label = text_label(raw_text)
        conf = el.get("confidence")
        cells = [float(o["confidence"]) for o in ocr if o.get("confidence") is not None and _center_in(o["bbox"], bbox)]
        if cells:
            conf = round(min(float(conf) if conf is not None else 1.0, sum(cells) / len(cells)), 3)
        item = {
            "label": label,
            "bbox": bbox,
            "raw_text": raw_text or "",
            "confidence": None if conf is None else round(float(conf), 3),
            "source": "docling",
            "raw": el,
        }
        if label == "picture" and el.get("figure") is not None:
            item["figure"] = int(el["figure"])
        if label == "table" and complex_tables:
            item["merged_cells"] = True  # Docling chỉ đếm số bảng gộp ô theo trang → gắn cho mọi bảng của trang
        out.append(item)
    return out


def _cu_box(item: dict, w: float, h: float) -> list[float] | None:
    polys = [pts for _pg, pts in parse_cu_source(item.get("source", ""))]
    for br in item.get("boundingRegions") or []:
        if br.get("polygon"):
            polys.append([float(x) for x in br["polygon"]])
    boxes = []
    for pts in polys:
        xs, ys = pts[0::2], pts[1::2]
        boxes.append([min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h])
    if not boxes:
        return None
    return [round(min(1.0, max(0.0, v)), 4) for v in union(boxes)]


def from_cu(raw: dict, docling_meta: dict | None = None) -> list[dict]:
    contents = ((raw or {}).get("result") or {}).get("contents") or []
    if not contents:
        return []
    content = contents[0]
    pages = content.get("pages") or []
    pg = pages[0] if pages else {}
    w, h = float(pg.get("width") or 0), float(pg.get("height") or 0)
    if w <= 0 or h <= 0:
        return []
    words = []
    for wd in pg.get("words") or []:
        box = _cu_box(wd, w, h)
        if box:
            conf = wd.get("confidence")
            words.append(Tok(str(wd.get("content", "")), box, None if conf is None else float(conf)))

    out: list[dict] = []
    regions: list[dict] = []  # bảng / hình: chữ bên trong thuộc về chúng
    for tb in content.get("tables") or []:
        box = _cu_box(tb, w, h)
        if not box:
            continue
        cells = tb.get("cells") or []
        merged = any((c.get("rowSpan") or 1) > 1 or (c.get("columnSpan") or 1) > 1 for c in cells)
        regions.append(
            {
                "label": "table",
                "bbox": box,
                "raw_text": "\n".join(str(c.get("content", "")) for c in cells),
                "source": "cu",
                "merged_cells": merged,
                "raw": {k: v for k, v in tb.items() if k != "cells"} | {"n_cells": len(cells)},
            }
        )
    for i, fg in enumerate(content.get("figures") or []):
        box = _cu_box(fg, w, h)
        if box:
            regions.append(
                {
                    "label": "picture",
                    "bbox": box,
                    "raw_text": str(fg.get("description") or ""),
                    "source": "cu",
                    "figure": i,
                    "raw": fg,
                }
            )
    # Hình Docling đã tìm thấy (CU mock / CU không trả figures) → vẫn có khung hình
    for el in (docling_meta or {}).get("elements") or []:
        if el.get("label") != "picture" or el.get("removed") or not el.get("bbox"):
            continue
        if any(r["label"] == "picture" and iou(r["bbox"], el["bbox"]) > 0.3 for r in regions):
            continue
        item = {
            "label": "picture",
            "bbox": [round(float(v), 4) for v in el["bbox"]],
            "raw_text": "",
            "source": "docling",
            "confidence": el.get("confidence"),
            "raw": el,
        }
        if el.get("figure") is not None:
            item["figure"] = int(el["figure"])
        regions.append(item)

    def owner(box):
        return next((r for r in regions if _center_in(box, r["bbox"])), None)

    free: list[Tok] = []
    for t in words:
        r = owner(t.bbox)
        if r is None:
            free.append(t)
        else:
            r.setdefault("_toks", []).append(t)
    for r in regions:
        toks = r.pop("_toks", [])
        if toks:
            if not r["raw_text"]:
                r["raw_text"] = _toks_text(toks)
            elif r["label"] == "picture":
                r["raw_text"] += "\n" + _toks_text(toks)
            r["confidence"] = token_confidence(toks)
        r.setdefault("confidence", None)
        out.append(r)

    paragraphs = content.get("paragraphs") or []
    if paragraphs:
        for para in paragraphs:
            box = _cu_box(para, w, h)
            if not box or owner(box) is not None:
                continue
            text = str(para.get("content", ""))
            role = para.get("role") or ""
            label = CU_ROLES.get(role) or text_label(text)
            toks = [t for t in free if _center_in(t.bbox, box)]
            out.append(
                {
                    "label": label,
                    "bbox": box,
                    "raw_text": text,
                    "confidence": token_confidence(toks),
                    "source": "cu",
                    "raw": para,
                }
            )
    else:
        for b in blocks_from_lines(group_lines(free), "cu"):
            b["raw"] = {"engine": "cu", "lines": b["raw"]["lines"]}
            out.append(b)
    return out


# ================================================================== thứ tự đọc
def reading_order(els: list[dict]) -> list[dict]:
    """Trên → dưới theo hàng (hai phần tử cùng hàng khi chồng nhau ≥ 50% chiều cao nhỏ hơn); trong một hàng chia
    cột theo phần chồng ngang, cột trái trước, trong cột trên → dưới."""
    rows: list[dict] = []
    for e in sorted(els, key=lambda e: (e["bbox"][1], e["bbox"][0])):
        b = e["bbox"]
        if rows:
            r = rows[-1]
            ov = min(r["y1"], b[3]) - max(r["y0"], b[1])
            hmin = min(r["y1"] - r["y0"], b[3] - b[1])
            if hmin > 0 and ov >= 0.5 * hmin:
                r["items"].append(e)
                r["y1"] = max(r["y1"], b[3])
                continue
        rows.append({"y0": b[1], "y1": b[3], "items": [e]})
    out = []
    for r in rows:
        cols: list[list[dict]] = []
        for e in sorted(r["items"], key=lambda e: e["bbox"][0]):
            for col in cols:
                if any(min(x["bbox"][2], e["bbox"][2]) - max(x["bbox"][0], e["bbox"][0]) > 0 for x in col):
                    col.append(e)
                    break
            else:
                cols.append([e])
        cols.sort(key=lambda col: min(x["bbox"][0] for x in col))
        for col in cols:
            out.extend(sorted(col, key=lambda x: x["bbox"][1]))
    return out


# ================================================================== gán Markdown cho phần tử
@dataclass
class Unit:
    text: str
    sep: str  # khoảng cách trước khối: "" (đầu trang) | "\n" | "\n\n"
    kind: str  # line | table | code | figure
    figure: int | None = None


def md_units(md: str) -> list[Unit]:
    """Markdown → khối nhỏ nhất không được tách: một dòng, một bảng, một khối ```, chú thích hình + mô tả."""
    lines = (md or "").replace("\r", "").split("\n")
    units: list[Unit] = []
    sep = ""
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            if units:
                sep = "\n\n"
            i += 1
            continue
        cur_sep = sep if units else ""
        if s.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            block = "\n".join(x.rstrip() for x in lines[i : j + 1]).rstrip()
            if units and units[-1].kind == "figure" and cur_sep == "\n":
                units[-1].text += "\n" + block
            else:
                units.append(Unit(block, cur_sep, "code"))
            i = j + 1
        elif s.startswith("|"):
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            units.append(Unit("\n".join(x.rstrip() for x in lines[i:j]), cur_sep, "table"))
            i = j
        else:
            m = _FIGURE.match(s)
            if m:
                units.append(Unit(lines[i].rstrip(), cur_sep, "figure", int(m.group(1))))
            elif units and units[-1].kind == "figure" and cur_sep == "\n":
                units[-1].text += "\n" + lines[i].rstrip()  # mô tả hình viết liền sau chú thích
            else:
                units.append(Unit(lines[i].rstrip(), cur_sep, "line"))
            i += 1
        sep = "\n"
    return units


def _grams(s: str) -> set[str]:
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


MATCH_MIN = 0.34  # khối Markdown phải trùng ≥ 34% bigram với chữ thô của phần tử mới được gán


def align(els: list[dict], md: str) -> list[dict]:
    """Gán từng khối Markdown cho phần tử (đã sắp thứ tự đọc). Khối không khớp đi theo khối trước nó. Phần tử không
    được khối nào nhưng chữ nằm trong khối của phần tử kề bên → gộp vào phần tử đó. Trả danh sách mới."""
    units = md_units(md)
    norms = [norm_text(e.get("raw_text", "")) for e in els]
    grams = [_grams(x) for x in norms]
    chars = [set(x) for x in norms]
    # phần chữ thô của phần tử đã được khối trước "dùng" → khối sau so với phần còn lại (tránh dồn hết vào một phần tử)
    used_g: list[set[str]] = [set() for _ in els]
    used_c: list[set[str]] = [set() for _ in els]
    has_table = any(e["label"] == "table" for e in els)
    assign: list[int | None] = [None] * len(units)
    used: set[int] = set()
    cursor = 0
    for ui, u in enumerate(units):
        best: int | None = None
        if u.kind in ("figure", "code"):
            pics = [i for i, e in enumerate(els) if e["label"] == "picture"]
            exact = [i for i in pics if u.figure is not None and els[i].get("figure") == u.figure]
            free = [i for i in pics if i not in used]
            best = (exact or free or [None])[0]
        if best is None and u.kind != "figure":
            un = norm_text(u.text)
            ug, uc = _grams(un), set(un)
            scored = []
            for i, eg in enumerate(grams):
                if not ug or not eg:
                    continue
                # trùng bigram (thứ tự chữ) + trùng ký tự (chịu được chữ bị đảo thứ tự trong kết quả OCR)
                cov = 0.35 * len(ug & (eg - used_g[i])) / len(ug) + 0.65 * len(uc & (chars[i] - used_c[i])) / len(uc)
                adj = cov - (0.15 if i < cursor else 0.0) - min(0.3, 0.06 * max(0, i - cursor - 1))
                if i in used and i != cursor:
                    adj -= 0.1
                if u.kind == "table" and els[i]["label"] == "table":
                    adj += 0.1
                scored.append((adj, -abs(i - cursor), cov, i))
            if scored:
                adj, _d, cov, i = max(scored)
                if cov >= MATCH_MIN:
                    best = i
            if best is None and u.kind == "table" and has_table:
                tables = [i for i, e in enumerate(els) if e["label"] == "table"]
                best = next((i for i in tables if i not in used), tables[0])
        assign[ui] = best
        if best is not None:
            used.add(best)
            cursor = best
            un = norm_text(u.text)
            used_g[best] |= _grams(un)
            used_c[best] |= set(un)

    if els and units:
        first = next((a for a in assign if a is not None), None)
        if first is None:
            # Không khối nào khớp chữ của phần tử (vd phần tử Docling chỉ có khung, không có chữ thô): chia các khối
            # lần lượt cho phần tử theo thứ tự đọc — vẫn giữ khung thật thay vì vỡ (out[None])
            n_el = len(els)
            assign = [min(n_el - 1, ui * n_el // len(units)) for ui in range(len(units))]
        prev = first if first is not None else assign[0]
        for ui in range(len(units)):
            if assign[ui] is None:
                assign[ui] = prev
            prev = assign[ui]
    elif units:  # không có phần tử nào (không có nguồn hình học) → mỗi khối một phần tử, chia đều theo chiều dọc
        n = len(units)
        els = [
            {
                "label": "text",
                "bbox": [0.0, round(i / n, 4), 1.0, round((i + 1) / n, 4)],
                "raw_text": u.text,
                "confidence": None,
                "source": "pdfium",
                "raw": {"engine": "markdown"},
            }
            for i, u in enumerate(units)
        ]
        assign = list(range(n))

    out = [dict(e, text="", sep="\n\n") for e in els]
    seen: set[int] = set()
    for u, a in zip(units, assign, strict=True):
        e = out[a]
        if a not in seen:
            e["text"], e["sep"] = u.text, (u.sep or "\n\n")
            seen.add(a)
        else:
            e["text"] += (u.sep or "\n") + u.text

    # Phần tử rỗng có chữ nằm trong khối của phần tử kề bên (vd 2 dòng PDF bị nối thành 1 dòng Markdown) → gộp
    drop: set[int] = set()
    for i, e in enumerate(out):
        if i in seen or e["label"] == "picture":
            continue
        raw_norm = norm_text(e.get("raw_text", ""))
        g = _grams(raw_norm)
        if not g:
            continue
        left = [k for k in range(i - 1, -1, -1) if k not in drop][:2]
        right = [k for k in range(i + 1, len(out)) if k not in drop][:2]
        cands = [k for pair in zip(left + [None] * 2, right + [None] * 2, strict=False) for k in pair if k is not None]
        for j in cands:
            if j in seen:
                other = norm_text(out[j]["text"])
                if len(raw_norm) >= 2:
                    cov = len(g & _grams(other)) / len(g)
                else:  # 1 ký tự (vd gạch ngang): chỉ gộp khi cùng hàng
                    ob = out[j]["bbox"]
                    same_row = min(ob[3], e["bbox"][3]) - max(ob[1], e["bbox"][1]) > 0
                    cov = float(same_row and raw_norm in other)
                if cov >= 0.6:
                    t = out[j]
                    t["bbox"] = union([t["bbox"], e["bbox"]])
                    confs = [x for x in (t.get("confidence"), e.get("confidence")) if x is not None]
                    t["confidence"] = min(confs) if confs else None
                    t["raw_text"] = (
                        (t["raw_text"] + "\n" + e["raw_text"]) if j < i else (e["raw_text"] + "\n" + t["raw_text"])
                    )
                    t.setdefault("merged_from", []).append(e.get("raw"))
                    drop.add(i)
                    break
    out = [e for i, e in enumerate(out) if i not in drop]
    for e in out:
        _refine_label(e)
    return out


def _refine_label(e: dict) -> None:
    text = e.get("text", "").strip()
    b = e["bbox"]
    if not text:
        # Chữ bị bỏ khi nối trang (header/footer lặp lại, số trang) → coi là header/footer, không phải mất chữ
        raw = e.get("raw_text", "").strip()
        if e["label"] not in ("picture", "table") and raw and len(raw) <= 60:
            if b[1] < 0.12 or _PAGE_NO.match(raw) and b[1] < 0.5:
                e["label"] = "page_header"
            elif b[3] > 0.88 or _PAGE_NO.match(raw):
                e["label"] = "page_footer"
        return
    if e["label"] in ("text", "list", "toc"):
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if lines and all(ln.startswith("|") for ln in lines):
            e["label"] = "table"
        elif lines and lines[0].startswith("# ") and len(lines) == 1:
            e["label"] = "title"
        elif lines and lines[0].startswith("#") and len(lines) == 1:
            e["label"] = "section_header"


# ================================================================== lắp ráp
def build_page_elements(
    *,
    markdown: str,
    cu_raw: dict | None = None,
    docling_meta: dict | None = None,
    tokens: list[Tok] | None = None,
    complex_tables: int = 0,
) -> list[dict]:
    """Phần tử cuối cùng (chưa có điểm yếu / trạng thái): id e1..eN theo thứ tự đọc, text = Markdown của vùng."""
    els: list[dict] = []
    if cu_raw:
        els = from_cu(cu_raw, docling_meta)
    if not els and (docling_meta or {}).get("engine") == "docling" and (docling_meta or {}).get("elements"):
        els = from_docling(docling_meta or {}, tokens or [], complex_tables)
    if not els:
        els = from_pdfium(tokens or [])
    els = align(reading_order(els), markdown)
    for i, e in enumerate(els, start=1):
        e["id"], e["order"] = f"e{i}", i
        e.setdefault("confidence", None)
        if e["label"] not in LABELS:
            e["label"] = "text"
    return els


def rebuild_markdown(els: list[dict]) -> str:
    """Ghép Markdown của các phần tử theo thứ tự đọc (giữ khoảng cách dòng gốc giữa các khối)."""
    out = ""
    for e in sorted(els, key=lambda e: e.get("order", 0)):
        t = (e.get("text") or "").strip("\n")
        if not t.strip():
            continue
        if out:
            out += e.get("sep") or "\n\n"
        out += t
    return out.strip() + "\n" if out.strip() else ""


def is_content(e: dict[str, Any]) -> bool:
    return e.get("label") not in HEADER_FOOTER
