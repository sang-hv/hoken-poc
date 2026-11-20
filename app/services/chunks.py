"""Review chunk: sửa, gộp, tách, duyệt. Mọi chunk đều phải được người duyệt trước khi index."""

from __future__ import annotations

from app.core.text import nfkc
from app.domain.models import Chunk, ChunkStatus, DocStatus
from app.domain.options import ChunkOptions
from app.services.container import Container
from app.services.jobs import emit
from app.services.pipeline import PipelineError, chunk_flag_threshold, chunk_flagged, refresh_doc, start_index
from app.steps import rules


def _require_review(c: Container, doc_id: str):
    doc = c.repo.get_doc(doc_id)
    if not doc:
        raise PipelineError("doc_not_found")
    if doc.status not in (DocStatus.chunk_review, DocStatus.indexed):
        raise PipelineError("doc_not_in_chunk_review")
    return doc


def _recheck(chunk: Chunk, opts: ChunkOptions) -> Chunk:
    lines = [rules.Line(t, chunk.page_from) for t in chunk.text.split("\n")]
    v = rules.validate_spans(lines, [rules.ChunkSpan(0, len(lines) - 1, chunk.item_code, chunk.title)], opts)
    chunk.violations = sorted({x for codes in v.values() for x in codes if x != "too_short"})
    chunk.rule_score = rules.rule_score(chunk.violations)
    if chunk.llm_score is None:
        chunk.confidence = chunk.rule_score
    else:
        chunk.confidence = round((chunk.rule_score + chunk.llm_score) / 2, 3)
    return chunk


def _back_to_review(c: Container, doc) -> None:
    if doc.status == DocStatus.indexed:
        refresh_doc(c, doc, DocStatus.chunk_review)
    else:
        refresh_doc(c, doc)


def _after_edit(c: Container, doc, actor: str) -> None:
    """Sau khi sửa / gộp / tách chunk. Duyệt tay: quay lại chunk_review chờ duyệt. Tự chạy (auto_review): người sửa
    coi như đã duyệt → duyệt luôn chunk vừa đổi rồi index lại, chat dùng được nội dung mới ngay."""
    if not doc.auto_review or doc.review_hold == "chunk":  # duyệt tay / đang dừng ở チャンクレビュー (warn)
        _back_to_review(c, doc)
        return
    for x in c.repo.list_chunks(doc.id):
        if x.status == ChunkStatus.draft:
            x.status = ChunkStatus.approved
            c.repo.save_chunk(x)
    refresh_doc(c, doc, DocStatus.chunk_review)
    emit(c, doc.id, "auto.reindex", by=actor)
    try:
        start_index(c, doc.id, actor)
    except PipelineError as e:  # chưa cấu hình embedding/search → để chunk_review, bấm index sau
        emit(c, doc.id, "job.blocked", "warn", step="index", reason=e.code)


def update_chunk(
    c: Container,
    doc_id: str,
    chunk_id: str,
    *,
    text: str,
    item_code: str,
    title: str,
    page_from: int | None,
    page_to: int | None,
    actor: str,
) -> Chunk:
    doc = _require_review(c, doc_id)
    ch = c.repo.get_chunk(doc_id, chunk_id)
    if not ch:
        raise PipelineError("chunk_not_found")
    ch.text, ch.item_code, ch.title = text.strip(), item_code.strip(), title.strip()
    if page_from:
        ch.page_from = page_from
    if page_to:
        ch.page_to = max(page_to, ch.page_from)
    ch.status, ch.edited_by = ChunkStatus.draft, actor
    _recheck(ch, c.config.pipeline()[1].chunk)
    c.repo.save_chunk(ch)
    emit(c, doc_id, "chunk.edited", chunk=chunk_id, by=actor)
    _after_edit(c, doc, actor)
    return ch


def _resequence(c: Container, doc_id: str) -> list[Chunk]:
    chunks = c.repo.list_chunks(doc_id)
    for i, ch in enumerate(chunks, start=1):
        if ch.seq != i:
            ch.seq = i
            c.repo.save_chunk(ch)
    return chunks


def merge_chunks(c: Container, doc_id: str, ids: list[str], actor: str) -> Chunk:
    doc = _require_review(c, doc_id)
    chunks = c.repo.list_chunks(doc_id)
    sel = [x for x in chunks if x.id in set(ids)]
    if len(sel) < 2:
        raise PipelineError("merge_needs_two")
    seqs = [x.seq for x in sel]
    if max(seqs) - min(seqs) != len(sel) - 1:
        raise PipelineError("merge_not_adjacent")
    first = sel[0]
    first.text = "\n\n".join(x.text for x in sel)
    first.page_from, first.page_to = min(x.page_from for x in sel), max(x.page_to for x in sel)
    first.item_code = first.item_code or next((x.item_code for x in sel if x.item_code), "")
    first.sections = list(dict.fromkeys(k for x in sel for k in x.sections))  # hợp khoá mục (giữ thứ tự)
    first.llm_score, first.status, first.edited_by = None, ChunkStatus.draft, actor
    _recheck(first, c.config.pipeline()[1].chunk)
    c.repo.save_chunk(first)
    for x in sel[1:]:
        c.repo.delete_chunk(doc_id, x.id)
    _resequence(c, doc_id)
    emit(c, doc_id, "chunk.merged", chunks=len(sel), by=actor)
    _after_edit(c, doc, actor)
    return first


def split_chunk(c: Container, doc_id: str, chunk_id: str, offset: int, actor: str) -> list[Chunk]:
    doc = _require_review(c, doc_id)
    ch = c.repo.get_chunk(doc_id, chunk_id)
    if not ch:
        raise PipelineError("chunk_not_found")
    a, b = ch.text[:offset].strip(), ch.text[offset:].strip()
    if not a or not b:
        raise PipelineError("split_empty")
    chunks = c.repo.list_chunks(doc_id)
    new_id = f"c{max(int(x.id[1:]) for x in chunks if x.id[1:].isdigit()) + 1:05d}"
    opts = c.config.pipeline()[1].chunk
    ch.text, ch.status, ch.edited_by, ch.llm_score = a, ChunkStatus.draft, actor, None
    second = Chunk(
        id=new_id,
        doc_id=doc_id,
        seq=ch.seq + 1,
        item_code=ch.item_code,
        title=ch.title,
        text=b,
        page_from=ch.page_to,
        page_to=ch.page_to,
        edited_by=actor,
        sections=list(ch.sections),
    )
    for x in chunks:
        if x.seq > ch.seq:
            x.seq += 1
            c.repo.save_chunk(x)
    c.repo.save_chunk(_recheck(ch, opts))
    c.repo.save_chunk(_recheck(second, opts))
    emit(c, doc_id, "chunk.split", chunk=chunk_id, by=actor)
    _after_edit(c, doc, actor)
    return [ch, second]


def approve_chunks(c: Container, doc_id: str, ids: list[str], approved: bool, actor: str) -> int:
    doc = _require_review(c, doc_id)
    n = 0
    for x in c.repo.list_chunks(doc_id):
        if x.id in set(ids):
            want = ChunkStatus.approved if approved else ChunkStatus.draft
            if x.status != want:
                x.status = want
                x.edited_by = actor
                c.repo.save_chunk(x)
                n += 1
    emit(c, doc_id, "chunk.approved" if approved else "chunk.unapproved", count=n, by=actor)
    c.repo.audit(actor, "chunk.approve" if approved else "chunk.unapprove", doc_id, count=n)
    _back_to_review(c, doc)
    return n


# ================================================================ danh sách chunk (tab チャンク), phân trang ở server
PREVIEW_CHARS = 120
LIST_MAX = 200


def _preview(text: str) -> str:
    one = " ".join(text.replace("|", " ").replace("#", " ").split())
    return one[:PREVIEW_CHARS]


def chunk_summary(ch: Chunk, threshold: float) -> dict:
    """Dòng danh sách: không có nội dung đầy đủ (chỉ preview) để tài liệu nhiều chunk vẫn nhẹ."""
    return {
        "id": ch.id,
        "seq": ch.seq,
        "item_code": ch.item_code,
        "title": ch.title,
        "preview": _preview(ch.text),
        "page_from": ch.page_from,
        "page_to": ch.page_to,
        "confidence": ch.confidence,
        "violations": ch.violations,
        "status": ch.status.value,
        "flagged": chunk_flagged(ch, threshold),
        "updated_at": ch.updated_at,
    }


def list_chunk_summaries(
    c: Container,
    doc_id: str,
    *,
    offset: int = 0,
    limit: int = 100,
    q: str = "",
    flt: str = "all",
    book_page: int | None = None,
    focus: str = "",
) -> dict:
    """Danh sách chunk theo thứ tự, lọc (all | issues = cần xem), tìm (mã mục / tiêu đề / nội dung, NFKC, không phân
    biệt hoa thường), lọc theo trang sách; trả một khối [offset, offset+limit) + tổng + số đếm. `focus` → vị trí của
    chunk đó trong danh sách đã lọc (để UI cuộn tới). PoC: lọc trong bộ nhớ — đủ nhanh tới vài chục nghìn chunk."""
    th = chunk_flag_threshold(c)
    chunks = c.repo.list_chunks(doc_id)
    issues = sum(1 for x in chunks if chunk_flagged(x, th))
    sel = chunks
    if flt == "issues":
        sel = [x for x in sel if chunk_flagged(x, th)]
    if book_page is not None:
        sel = [x for x in sel if x.page_from <= book_page <= x.page_to]
    needle = nfkc(q).lower().strip()
    if needle:
        sel = [x for x in sel if needle in nfkc(f"{x.item_code} {x.title} {x.text}").lower()]
    limit = max(1, min(LIST_MAX, limit))
    offset = max(0, offset)
    focus_index = next((i for i, x in enumerate(sel) if x.id == focus), None) if focus else None
    return {
        "total": len(sel),
        "counts": {"all": len(chunks), "issues": issues},
        "offset": offset,
        "items": [chunk_summary(x, th) for x in sel[offset : offset + limit]],
        "focus_index": focus_index,
    }
