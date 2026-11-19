"""Logic thuần (không I/O): định tuyến, nối trang, cắt thô, kiểm tra luật chunk. Test trực tiếp bằng pytest."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from app.domain.models import Page
from app.domain.options import ChunkOptions, RoutingOptions, StitchOptions


# ================================================================== định tuyến
def decide_route(page: Page, opts: RoutingOptions) -> tuple[str, list[str]]:
    """Trang dễ khi thoả mọi điều kiện; ngược lại trả về 'hard' kèm lý do."""
    if page.route_override == "force_cu":
        return "hard", ["override_force_cu"]
    if page.route_override == "skip_cu":
        return "easy", ["override_skip_cu"]
    s, f = page.scores, page.features
    reasons: list[str] = []
    if page.engine != "docling":
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
