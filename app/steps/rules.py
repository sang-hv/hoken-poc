"""Logic thuần (không I/O): định tuyến, nối trang, cắt thô, kiểm tra luật chunk. Test trực tiếp bằng pytest."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import Page
from app.domain.options import ChunkOptions, RoutingOptions, StitchOptions
from app.steps.parser import PARSER_ENGINES


# ================================================================== định tuyến
def decide_route(page: Page, opts: RoutingOptions) -> tuple[str, list[str]]:
    """Trang dễ khi thoả mọi điều kiện; ngược lại trả về 'hard' kèm lý do."""
    if page.route_override == "force_cu":
        return "hard", ["override_force_cu"]
    if page.route_override == "skip_cu":
        return "easy", ["override_skip_cu"]
    s, f = page.scores, page.features
    reasons: list[str] = []
    if page.engine not in PARSER_ENGINES:  # fallback pdfium: không có điểm parser
        reasons.append("no_docling")
    else:
        if s.low_score is None or s.low_score < opts.min_low_score:
            reasons.append("low_grade")
        if s.parse_score is not None and s.parse_score < opts.min_parse_score:
            reasons.append("parse_score")
        if opts.ocr_page_is_hard and s.ocr_score is not None:
            reasons.append("ocr")
    if not f.has_text_layer:
        reasons.append("scanned")
    if opts.complex_table_is_hard and f.complex_tables > 0:
        reasons.append("complex_table")
    if opts.table_crossing_page_is_hard and (f.table_at_bottom or f.table_at_top):
        reasons.append("table_cross_page")
    if f.max_figure_area > opts.figure_min_area:
        reasons.append("figure")
    return ("hard" if reasons else "easy"), reasons


# ================================================================== nối dòng bị ngắt (fallback pdfium)
_LINE_START = re.compile(
    r"^(\d+\s|[0-9０-９]+[.)．）]|注|・|※|[（(]|#|\||[A-Z]\d{3}|ただし|なお|[-－—–‐]?\s*\d{1,4}\s*[-－—–‐]?$)"
)


def join_wrapped_lines(text: str, min_len: int = 25) -> str:
    """pdfium trả về từng dòng hiển thị; nối các dòng bị ngắt giữa câu (không đụng bảng, mục, ghi chú)."""
    out: list[str] = []
    for ln in text.split("\n"):
        cur = ln.rstrip()
        if out and cur.strip() and out[-1].strip():
            prev = out[-1]
            if (
                len(prev.strip()) >= min_len
                and not prev.rstrip().endswith(_SENT_END)
                and not _LINE_START.match(cur.strip())
            ):
                sep = " " if prev[-1:].isascii() and cur.strip()[:1].isascii() else ""
                out[-1] = prev + sep + cur.strip()
                continue
        out.append(cur)
    return "\n".join(out)


# ================================================================== nối trang
_PAGE_NO = re.compile(r"^[\s\-－—–‐(（]*\d{1,4}[\s\-－—–‐)）]*$")
_SENT_END = ("。", "．", ".", ":", "：", "」", "）", ")", "】")


def _header_candidate(line: str) -> bool:
    """Header/footer chỉ là dòng ngắn, không phải dòng bảng (dòng tiêu đề bảng lặp lại phải giữ)."""
    t = line.strip()
    return bool(t) and not t.startswith("|") and len(t) <= 60


def _norm_line(s: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", "", s))


@dataclass
class StitchResult:
    texts: dict[int, str]
    removed: dict[int, int]  # trang → số dòng header/footer bị bỏ
    continues_next: dict[int, bool] = field(default_factory=dict)
    table_continues_next: dict[int, bool] = field(default_factory=dict)


def stitch_pages(pages: dict[int, str], opts: StitchOptions) -> StitchResult:
    order = sorted(pages)
    split = {p: pages[p].replace("\r", "").split("\n") for p in order}
    cand: Counter[str] = Counter()
    for p in order:
        lines = [ln for ln in split[p] if ln.strip()]
        edge = lines[: opts.header_lines] + lines[-opts.footer_lines :] if lines else []
        cand.update({_norm_line(ln) for ln in edge if _header_candidate(ln)})
    threshold = max(2, int(len(order) * opts.repeat_ratio + 0.999)) if len(order) >= 3 else 10**9
    repeated = {k for k, n in cand.items() if n >= threshold and k}

    texts, removed, cont, tcont = {}, {}, {}, {}
    for p in order:
        lines = split[p]
        nonempty = [i for i, ln in enumerate(lines) if ln.strip()]
        edge_idx = set(nonempty[: opts.header_lines] + nonempty[-opts.footer_lines :])
        keep = []
        n_removed = 0
        for i, ln in enumerate(lines):
            if (
                i in edge_idx
                and _header_candidate(ln)
                and (_norm_line(ln) in repeated or _PAGE_NO.match(ln.strip() or "x"))
            ):
                n_removed += 1
                continue
            keep.append(ln)
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip() + "\n"
        texts[p], removed[p] = text, n_removed
    for a, b in zip(order, order[1:], strict=False):
        last = [ln for ln in texts[a].split("\n") if ln.strip()]
        first = [ln for ln in texts[b].split("\n") if ln.strip()]
        if not last or not first:
            continue
        la, fb = last[-1].strip(), first[0].strip()
        tcont[a] = la.startswith("|") and fb.startswith("|")
        cont[a] = (
            (not tcont[a])
            and not la.endswith(_SENT_END)
            and not la.startswith(("#", "|"))
            and not fb.startswith(("#", "|"))
        )
    return StitchResult(texts, removed, cont, tcont)


# ================================================================== cắt thô theo mã mục
@dataclass
class Line:
    text: str
    page: int  # trang trong sách


@dataclass
class Section:
    item_code: str
    title: str
    lines: list[Line]


_EXCEPTION_START = ("ただし", "但し", "なお", "この場合", "注）", "注)", "（注", "(注")


def item_code_pattern(opts: ChunkOptions) -> re.Pattern:
    code = opts.item_code_regex
    return re.compile(rf"^\s*(?:#{{1,6}}\s*)?(?:区分番号\s*)?[「\[【（(]?\s*({code})(?![\d-])\s*[」\]】）)]?\s*(.*)$")


def assemble_lines(page_texts: list[tuple[int, str, bool, bool]]) -> list[Line]:
    """page_texts: (trang sách, markdown, continues_next, table_continues_next) theo thứ tự trang.

    Gộp đoạn bị ngắt trang và bỏ dòng tiêu đề bảng bị lặp ở trang sau.
    """
    out: list[Line] = []
    prev_table_header: str | None = None
    prev_cont = prev_tcont = False
    for book_page, text, cont, tcont in page_texts:
        lines = [ln.rstrip() for ln in text.split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        if (
            prev_tcont
            and prev_table_header
            and len(lines) >= 2
            and lines[0].strip() == prev_table_header
            and re.match(r"^\|[\s:\-|]+\|$", lines[1].strip())
        ):
            lines = lines[2:]
        if prev_cont and out and lines and lines[0].strip():
            out[-1] = Line(out[-1].text + lines[0].strip(), out[-1].page)
            lines = lines[1:]
        for ln in lines:
            out.append(Line(ln, book_page))
        table_lines = [ln for ln in lines if ln.strip().startswith("|")]
        header = None
        for i, ln in enumerate(lines):
            if ln.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1].strip()):
                header = ln.strip()
        prev_table_header = header if table_lines else None
        prev_cont, prev_tcont = cont, tcont
    while out and not out[-1].text.strip():
        out.pop()
    return out


def rough_sections(lines: list[Line], opts: ChunkOptions) -> list[Section]:
    pat = item_code_pattern(opts)
    sections: list[Section] = []
    cur = Section("", "", [])
    for ln in lines:
        m = pat.match(ln.text)
        if m and not ln.text.strip().startswith("|"):
            if cur.lines and any(x.text.strip() for x in cur.lines):
                sections.append(cur)
            cur = Section(m.group(1), m.group(2).strip()[:120], [ln])
        else:
            cur.lines.append(ln)
    if cur.lines and any(x.text.strip() for x in cur.lines):
        sections.append(cur)
    return sections


# ================================================================== chunk & kiểm tra luật
@dataclass
class ChunkSpan:
    start: int  # chỉ số dòng trong section (0-based, gồm cả 2 đầu)
    end: int
    item_code: str
    title: str = ""


def table_blocks(lines: list[Line]) -> list[tuple[int, int]]:
    blocks, start = [], None
    for i, ln in enumerate(lines):
        is_t = ln.text.strip().startswith("|")
        if is_t and start is None:
            start = i
        if not is_t and start is not None:
            blocks.append((start, i - 1))
            start = None
    if start is not None:
        blocks.append((start, len(lines) - 1))
    return blocks


def _first_text(lines: list[Line], start: int, end: int) -> str:
    for i in range(start, end + 1):
        if lines[i].text.strip():
            return lines[i].text.strip()
    return ""


def validate_spans(lines: list[Line], spans: list[ChunkSpan], opts: ChunkOptions) -> dict[int, list[str]]:
    """Trả về {chỉ số chunk (-1 = toàn section): [vi phạm]}. Rỗng = đạt."""
    v: dict[int, list[str]] = {}

    def add(i, code):
        v.setdefault(i, []).append(code)

    n = len(lines)
    if not spans:
        add(-1, "no_chunks")
        return v
    expect = 0
    for s in spans:
        if s.start != expect or s.end < s.start or s.end >= n:
            add(-1, "coverage")
            break
        expect = s.end + 1
    else:
        if expect != n:
            add(-1, "coverage")
    if -1 in v:
        return v
    for a, b in table_blocks(lines):
        owners = {i for i, s in enumerate(spans) if not (s.end < a or s.start > b)}
        if len(owners) > 1:
            for i in owners:
                add(i, "table_split")
    for i, s in enumerate(spans):
        text = "\n".join(lines[j].text for j in range(s.start, s.end + 1)).strip()
        if not s.item_code:
            add(i, "no_item_code")
        if i > 0 and _first_text(lines, s.start, s.end).startswith(_EXCEPTION_START):
            add(i, "exception_separated")
        if len(text) > opts.max_chars * 1.5 and not any(a <= s.start and s.end <= b for a, b in table_blocks(lines)):
            add(i, "too_long")
        if len(text) < opts.min_chars and len(spans) > 1:
            add(i, "too_short")
    return v


SOFT = {"too_long", "too_short"}


def hard_violations(v: dict[int, list[str]]) -> int:
    return sum(1 for codes in v.values() for c in codes if c not in SOFT)


def deterministic_spans(section: Section, opts: ChunkOptions) -> list[ChunkSpan]:
    """Chia không cần LLM: theo đoạn trống, không cắt bảng, ngoại lệ đi cùng đoạn trước, ≤ max_chars."""
    lines = section.lines
    blocks: list[tuple[int, int]] = []
    tables = table_blocks(lines)
    i = 0
    while i < len(lines):
        t = next(((a, b) for a, b in tables if a == i), None)
        if t:
            blocks.append(t)
            i = t[1] + 1
            continue
        start = i
        while i < len(lines) and lines[i].text.strip() and not any(a == i for a, _ in tables):
            i += 1
        while i < len(lines) and not lines[i].text.strip():
            i += 1
        if i == start:
            i += 1
        blocks.append((start, i - 1))
    spans: list[ChunkSpan] = []
    size = 0
    for a, b in blocks:
        text_len = sum(len(lines[j].text) for j in range(a, b + 1))
        starts_exc = _first_text(lines, a, b).startswith(_EXCEPTION_START)
        if spans and (size + text_len <= opts.max_chars or starts_exc or size < opts.min_chars):
            spans[-1].end = b
            size += text_len
        else:
            spans.append(ChunkSpan(a, b, section.item_code, section.title))
            size = text_len
    return spans


def span_text(lines: list[Line], s: ChunkSpan) -> str:
    return "\n".join(lines[j].text for j in range(s.start, s.end + 1)).strip()


def rule_score(violations: list[str]) -> float:
    hard = sum(1 for c in violations if c not in SOFT)
    soft = len(violations) - hard
    return round(max(0.0, 1.0 - 0.3 * hard - 0.1 * soft), 3)


# ================================================================== vùng confidence thấp (viền đỏ ở màn review)
# Gom chữ của Content Understanding và phần tử của Docling về một dạng chung:
# {source, label, bbox[x0,y0,x1,y1] top-left 0..1, confidence, text, span}. Toạ độ CU
# (`source: "D(trang,x1,y1,...,x4,y4)"`) theo đơn vị của trang (inch với PDF) → chia width/height ra 0..1.

_SOURCE = re.compile(r"D\((\d+),([^)]*)\)")


def parse_cu_source(source: str) -> list[tuple[int, list[float]]]:
    """'D(1,x1,y1,...,x4,y4);D(...)' → [(trang, [x1, y1, ..., x4, y4])]. Bỏ qua phần không đúng dạng."""
    out = []
    for m in _SOURCE.finditer(source or ""):
        try:
            nums = [float(x) for x in m.group(2).split(",")]
        except ValueError:
            continue
        if len(nums) >= 4 and len(nums) % 2 == 0:
            out.append((int(m.group(1)), nums))
    return out


def _bbox(points: list[float], w: float, h: float) -> list[float]:
    xs, ys = points[0::2], points[1::2]
    clamp = lambda v: round(min(1.0, max(0.0, v)), 4)  # noqa: E731
    return [clamp(min(xs) / w), clamp(min(ys) / h), clamp(max(xs) / w), clamp(max(ys) / h)]


def _span(word: dict) -> list[int] | None:
    sp = word.get("span") or (word.get("spans") or [None])[0]
    if isinstance(sp, dict) and "offset" in sp and "length" in sp:
        return [int(sp["offset"]), int(sp["length"])]
    return None


def cu_low_words(raw: dict[str, Any], threshold: float) -> list[dict]:
    """Chữ trong kết quả CU (prebuilt-layout) có confidence < threshold. `span` trỏ vào markdown của CU."""
    contents = ((raw or {}).get("result") or {}).get("contents") or []
    out: list[dict] = []
    for content in contents:
        for pg in content.get("pages") or []:
            w, h = float(pg.get("width") or 0), float(pg.get("height") or 0)
            if w <= 0 or h <= 0:
                continue
            for word in pg.get("words") or []:
                conf = word.get("confidence")
                if conf is None or float(conf) >= threshold:
                    continue
                polys = parse_cu_source(word.get("source", ""))
                if not polys:
                    continue
                out.append(
                    {
                        "source": "cu",
                        "label": "word",
                        "text": str(word.get("content", "")),
                        "confidence": round(float(conf), 3),
                        "bbox": _bbox(polys[0][1], w, h),
                        "span": _span(word),
                    }
                )
    return out


def docling_low_elements(elements: list[dict], threshold: float) -> list[dict]:
    """Phần tử Docling (vùng layout, ô chữ OCR) có confidence < threshold. Phần tử đã loại (logo...) bỏ qua."""
    out = []
    for el in elements or []:
        conf = el.get("confidence")
        if conf is None or el.get("removed") or float(conf) >= threshold:
            continue
        out.append(
            {
                "source": "docling",
                "label": el.get("label", ""),
                "text": el.get("text", ""),
                "confidence": round(float(conf), 3),
                "bbox": el["bbox"],
                "span": None,
            }
        )
    return out


def low_confidence_boxes(docling_meta: dict | None, cu_raw: dict | None, threshold: float) -> list[dict]:
    """Ghép hai nguồn, thấp nhất lên trước để reviewer xem chỗ đáng ngờ nhất trước."""
    boxes = docling_low_elements((docling_meta or {}).get("elements", []), threshold) + cu_low_words(
        cu_raw or {}, threshold
    )
    return sorted(boxes, key=lambda b: b["confidence"])


# ================================================================== UI v2 — điểm yếu & chất lượng (tab 検査)
# Phần tử (element) là dict: {label, bbox, text (Markdown), raw_text (chữ đọc từ lớp text / OCR / CU),
# confidence, status, merged_cells?, reread_from?}. Hàm ở đây chỉ tính toán, không I/O.

HEADER_FOOTER = ("page_header", "page_footer")
DONE_STATUSES = ("fixed", "accepted")  # người (hoặc người bấm AI) đã xử lý → điểm yếu không còn "mở"
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_MD_NOISE = re.compile(r"[\s#*|>`_~\-－—–‐:：]+")
_TABLE_SEP = re.compile(r"^\|[\s:\-|]+\|$")


def visible_text(md: str) -> str:
    """Markdown bỏ chú thích HTML (vd `<!-- figure:0 -->`) và khoảng trắng hai đầu."""
    return _HTML_COMMENT.sub("", md or "").strip()


def norm_text(s: str) -> str:
    """Chuẩn hoá để so nội dung: NFKC, bỏ chú thích HTML, ký hiệu Markdown và khoảng trắng."""
    import unicodedata

    return _MD_NOISE.sub("", unicodedata.normalize("NFKC", _HTML_COMMENT.sub("", s or "")))


def md_table_rows(md: str) -> list[list[str]]:
    """Các hàng bảng Markdown (bỏ hàng phân cách `|---|`) → danh sách ô."""
    rows = []
    for ln in (md or "").split("\n"):
        s = ln.strip()
        if not s.startswith("|") or _TABLE_SEP.match(s):
            continue
        rows.append([x.strip() for x in s.strip("|").split("|")])
    return rows


def table_suspect_reason(el: dict, *, continues_prev: bool = False, continues_next: bool = False) -> str:
    """'' nếu bảng ổn; ngược lại lý do: not_table (đọc ra không phải bảng Markdown) · cols (số cột lệch giữa
    các hàng) · merged (bảng có ô gộp) · cross_page (bảng chạm mép trang và nối sang trang trước/sau)."""
    rows = md_table_rows(el.get("text", ""))
    if not rows:
        return "not_table"
    if len({len(r) for r in rows}) > 1:
        return "cols"
    if el.get("merged_cells"):
        return "merged"
    bb = el.get("bbox") or [0, 0, 1, 1]
    if (continues_next and bb[3] > 0.85) or (continues_prev and bb[1] < 0.15):
        return "cross_page"
    return ""


def element_weak_flags(
    el: dict, opts: Any, *, table_continues_prev: bool = False, table_continues_next: bool = False
) -> list[dict]:
    """Điểm yếu của một phần tử. `opts` là QualityOptions.

    - low_confidence: confidence < weak_confidence (error nếu < auto_vlm_below, còn lại warn)
    - picture_no_desc: hình chưa có mô tả (Markdown rỗng sau khi bỏ chú thích) — nếu bật picture_needs_description
    - missing_text: vùng có chữ (raw_text ≥ 4 ký tự) nhưng Markdown đọc ra < 30% độ dài đó
    Header / footer (page_header, page_footer) không có điểm yếu.
    - table_suspect: xem `table_suspect_reason`
    - reread: đã phải đọc lại bằng VLM (detail = confidence trước khi đọc lại)
    """
    label = el.get("label", "text")
    flags: list[dict] = []
    if label in HEADER_FOOTER:  # header / footer / số trang bị bỏ khi nối trang — không tính điểm yếu
        return flags
    conf = el.get("confidence")
    if conf is not None and float(conf) < opts.weak_confidence:
        sev = "error" if float(conf) < opts.auto_vlm_below else "warn"
        flags.append({"code": "low_confidence", "severity": sev, "detail": f"{float(conf):.2f}"})
    text_len = len(norm_text(el.get("text", "")))
    if label == "picture":
        if opts.picture_needs_description and not visible_text(el.get("text", "")):
            flags.append({"code": "picture_no_desc", "severity": "warn"})
    else:
        raw_len = len(norm_text(el.get("raw_text", "")))
        if raw_len >= 4 and text_len < 0.3 * raw_len:
            flags.append({"code": "missing_text", "severity": "error", "detail": f"{text_len}/{raw_len}"})
    if label == "table":
        why = table_suspect_reason(el, continues_prev=table_continues_prev, continues_next=table_continues_next)
        if why:
            flags.append({"code": "table_suspect", "severity": "warn", "detail": why})
    if el.get("reread_from") is not None:
        before = el["reread_from"]
        flags.append({"code": "reread", "severity": "warn", "detail": f"{float(before):.2f}" if before != "" else ""})
    return flags


def page_level_flag(
    elements: list[dict], page_markdown: str, opts: Any, *, scanned: bool, ocr_score: float | None
) -> dict | None:
    """Điểm yếu của cả trang (gắn vào phần tử nội dung đầu tiên của trang):
    - blank_page: Markdown của trang gần như rỗng (< 5 ký tự có nghĩa)
    - ocr_weak: trang scan (không có lớp text / phải OCR) và điểm OCR < weak_confidence; không có điểm OCR thì
      dùng confidence trung bình của các phần tử."""
    if len(norm_text(page_markdown)) < 5:
        return {"code": "blank_page", "severity": "error"}
    if not scanned:
        return None
    score = ocr_score
    if score is None:
        confs = [float(e["confidence"]) for e in elements if e.get("confidence") is not None]
        score = sum(confs) / len(confs) if confs else None
    if score is not None and score < opts.weak_confidence:
        return {"code": "ocr_weak", "severity": "warn", "detail": f"{score:.2f}"}
    return None


def element_status(flags: list[dict], current: str = "") -> str:
    """fixed / accepted giữ nguyên (người đã xử lý); còn lại weak nếu có điểm yếu, ok nếu không."""
    if current in DONE_STATUSES:
        return current
    return "weak" if flags else "ok"


# ------------------------------------------------------------------ kết quả nhận diện (docs/STATUS.md §C)
# Mã điểm yếu nghĩa là "nội dung chưa được đọc ra" → 未認識; mọi mã khác → 要確認.
UNREAD_CODES = frozenset({"missing_text", "blank_page", "picture_no_desc"})
BUCKETS = ("good", "fixed", "weak", "unread")  # fixed = người / AI theo yêu cầu đã sửa hoặc xác nhận


def flags_bucket(flags: list[dict]) -> str:
    """Nhóm theo danh sách điểm yếu (bỏ qua trạng thái người xử lý): unread > weak > good."""
    codes = {f.get("code") for f in flags}
    if codes & UNREAD_CODES:
        return "unread"
    return "weak" if codes else "good"


def element_bucket(el: dict) -> str | None:
    """Nhóm hiện tại của phần tử: fixed nếu người đã xử lý (fixed / accepted), không thì theo điểm yếu.
    Header / footer / số trang không tính → None."""
    if el.get("label") in HEADER_FOOTER:
        return None
    if el.get("status") in DONE_STATUSES:
        return "fixed"
    return flags_bucket(el.get("weak") or [])


def open_flags(el: dict) -> list[dict]:
    return [] if el.get("status") in DONE_STATUSES else list(el.get("weak") or [])


FLAG_PENALTY = {"error": 12, "warn": 5}
MAX_PENALTY = 60


def page_quality_score(elements: list[dict], vlm_score: float | None = None) -> int:
    """Điểm trang 0..100 (phạt theo điểm yếu còn mở):

    base    = 100 × trung bình confidence hiệu dụng của các phần tử nội dung (bỏ header/footer);
              phần tử fixed/accepted tính 1.0, phần tử không có confidence tính 0.95; trang không có phần tử
              nội dung → base = 100
    penalty = Σ điểm yếu còn mở: error 12, warn 5 (tối đa 60)
    score   = clamp(base − penalty, 0, 100)
    có điểm VLM (nút 「AIで採点」) → score = trung bình (score, điểm VLM)
    """
    content = [e for e in elements if e.get("label") not in HEADER_FOOTER]
    effs = []
    for e in content:
        if e.get("status") in DONE_STATUSES:
            effs.append(1.0)
        elif e.get("confidence") is None:
            effs.append(0.95)
        else:
            effs.append(max(0.0, min(1.0, float(e["confidence"]))))
    base = 100.0 * (sum(effs) / len(effs)) if effs else 100.0
    penalty = min(MAX_PENALTY, sum(FLAG_PENALTY.get(f.get("severity"), 5) for e in elements for f in open_flags(e)))
    score = max(0.0, min(100.0, base - penalty))
    if vlm_score is not None:
        score = (score + max(0.0, min(100.0, float(vlm_score)))) / 2
    return int(round(score))


def doc_quality_score(page_scores: list[int]) -> int:
    """Điểm tài liệu = 0.7 × trung bình điểm trang + 0.3 × điểm trang kém nhất (trang kém kéo điểm xuống).
    Không có trang nào → 0."""
    if not page_scores:
        return 0
    mean = sum(page_scores) / len(page_scores)
    return int(round(0.7 * mean + 0.3 * min(page_scores)))


def quality_grade(score: float, opts: Any) -> str:
    """good (良好) ≥ grade_good · fair (要注意) ≥ grade_fair · poor (不良)."""
    if score >= opts.grade_good:
        return "good"
    if score >= opts.grade_fair:
        return "fair"
    return "poor"


# ================================================================== chunk lại một phần
def section_keys(sections: list[Section]) -> list[str]:
    """Khoá ổn định của mục: mã mục + thứ tự trong các mục cùng mã ("M017#0", "_#0" cho phần không mã)."""
    seen: dict[str, int] = {}
    out = []
    for s in sections:
        k = s.item_code or "_"
        out.append(f"{k}#{seen.get(k, 0)}")
        seen[k] = seen.get(k, 0) + 1
    return out


def partial_plan(
    keys: list[str],
    section_pages: list[set[int]],
    changed: set[int],
    chunks: list[tuple[list[str], int, int]],
) -> tuple[set[str], set[int]] | None:
    """Chunk lại một phần sau khi sửa các trang `changed` (trang sách).

    keys / section_pages: các mục của văn bản MỚI và trang của từng mục. chunks: (khoá mục, page_from, page_to)
    của chunk hiện có theo thứ tự. Trả (khoá mục cần chunk lại, chỉ số chunk bị bỏ) hoặc None = chunk lại toàn
    bộ (có chunk cũ chưa có khoá). Bất biến: mọi chunk bị bỏ có mục được sinh lại (trừ mục đã biến mất) và mọi mục
    sinh lại thì chunk cũ của nó bị bỏ — không mất, không trùng nội dung. Hàm thuần.
    """
    if any(not secs for secs, _a, _b in chunks):
        return None
    new = set(keys)
    aff = {k for k, pages in zip(keys, section_pages, strict=True) if pages & changed}
    drop: set[int] = set()
    for i, (secs, a, b) in enumerate(chunks):
        if any(a <= p <= b for p in changed) or any(k not in new for k in secs):
            drop.add(i)
            aff |= set(secs) & new
    grew = True
    while grew:  # chunk gộp nhiều mục: bỏ một → bỏ cả nhóm và sinh lại mọi mục của nó
        grew = False
        for i, (secs, _a, _b) in enumerate(chunks):
            if i not in drop and set(secs) & aff:
                drop.add(i)
                grew = True
            if i in drop and not (set(secs) & new) <= aff:
                aff |= set(secs) & new
                grew = True
    return aff, drop


# ================================================================== chunk ↔ phần tử (tô vùng trên ảnh trang)
COVER_FULL = 0.8  # ≥ mức này: phần tử nằm trong chunk
COVER_PART = 0.3  # ≥ mức này: một phần phần tử nằm trong chunk (chunk tách giữa phần tử)


def chunk_coverage(chunk_text: str, elements: list[dict]) -> dict[str, float]:
    """Tỉ lệ nội dung của từng phần tử có trong chunk (0..1), theo từng dòng đã chuẩn hoá (bỏ ký hiệu Markdown,
    khoảng trắng — chunk được nối từ nhiều trang / dòng nên so theo dòng con). Bỏ header/footer và dòng < 2 ký
    tự (số trang, "1"…) để không khớp nhầm. Chỉ trả phần tử ≥ COVER_PART. Hàm thuần."""
    hay = norm_text(chunk_text)
    out: dict[str, float] = {}
    for e in elements:
        if e.get("label") in HEADER_FOOTER:
            continue
        lines = [x for x in (norm_text(ln) for ln in (e.get("text") or "").split("\n")) if len(x) >= 2]
        total = sum(len(x) for x in lines)
        if not total:
            continue
        r = sum(len(x) for x in lines if x in hay) / total
        if r >= COVER_PART:
            out[e["id"]] = round(r, 3)
    return out
