"""Vòng đời tài liệu: upload, chuyển trạng thái, fan-in (đủ trang mới nối), review OCR, review chunk."""

from __future__ import annotations

from app.core.util import new_id, now_iso
from app.domain.models import (
    ChunkStatus,
    DocStatus,
    Document,
    Job,
    JobStatus,
    Page,
    PageStatus,
    PageVersion,
    page_key,
)
from app.services.container import Container
from app.services.jobs import emit, enqueue
from app.steps.common import k_page, k_source, k_version, pdf_page_count

PRE_REVIEW = {PageStatus.queued, PageStatus.docling, PageStatus.routed, PageStatus.cu, PageStatus.ready}


class PipelineError(ValueError):
    """Lỗi do thao tác không hợp lệ (trả 400/409 cho UI)."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


# ================================================================== upload
def to_pdf(data: bytes) -> tuple[bytes, str]:
    """PDF giữ nguyên; PNG/JPEG → PDF 1 trang (cạnh dài ≈ A4 khi render 72 dpi, ảnh gốc giữ nguyên độ phân giải)."""
    if data.startswith(b"%PDF"):
        return data, "pdf"
    if not (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")):
        raise PipelineError("unsupported_file")
    import io

    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise PipelineError("bad_image") from e
    resolution = max(72.0, max(img.size) * 72.0 / 842.0)
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=resolution)
    return buf.getvalue(), "image"


def create_document(
    c: Container,
    *,
    data: bytes,
    filename: str,
    name: str,
    kind: str,
    book_page_start: int,
    page_from: int | None,
    page_to: int | None,
    actor: str,
    auto_review: bool = False,
    file_type: str = "pdf",
) -> Document:
    if not data.startswith(b"%PDF"):
        raise PipelineError("not_pdf")
    total = pdf_page_count(data)
    pf = page_from or 1
    pt = page_to or total
    if not (1 <= pf <= pt <= total):
        raise PipelineError("bad_page_range", total=total)
    version, _ = c.config.pipeline()
    doc = Document(
        id=new_id(),
        name=name or filename,
        kind=kind,
        filename=filename,
        book_page_start=book_page_start,
        page_from=pf,
        page_to=pt,
        total_pdf_pages=total,
        created_by=actor,
        created_at=now_iso(),
        config_version=version,
        auto_review=auto_review,
        file_type=file_type,
        size_bytes=len(data),
    )
    c.blob.put(k_source(doc.id), data, "application/pdf")
    for p in range(pf, pt + 1):
        c.repo.save_page(Page(id=page_key(p), doc_id=doc.id, page=p, book_page=doc.book_page(p)))
    refresh_doc(c, doc)
    emit(c, doc.id, "doc.uploaded", pages=doc.n_pages, total=total, by=actor)
    c.repo.audit(actor, "document.upload", doc.id, pages=doc.n_pages)
    for p in range(pf, pt + 1):
        enqueue(c, doc.id, "docling", p, actor=actor)
    return doc


# ================================================================== trạng thái
def refresh_doc(c: Container, doc: Document | str, status: DocStatus | None = None) -> Document:
    if isinstance(doc, str):
        doc = c.repo.get_doc(doc)
    pages = c.repo.list_pages(doc.id)
    counts: dict[str, int] = {}
    for p in pages:
        counts[p.status.value] = counts.get(p.status.value, 0) + 1
    counts["hard"] = sum(1 for p in pages if p.route == "hard")
    counts["cu_skipped"] = sum(1 for p in pages if p.cu_status == "skipped")
    chunks = (
        c.repo.list_chunks(doc.id)
        if doc.status in (DocStatus.chunk_review, DocStatus.indexing, DocStatus.indexed, DocStatus.chunking)
        else []
    )
    if chunks:
        counts["chunks"] = len(chunks)
        counts["chunks_approved"] = sum(1 for x in chunks if x.status != ChunkStatus.draft)
        counts["chunks_indexed"] = sum(1 for x in chunks if x.status == ChunkStatus.indexed)
    doc.stats = counts
    if status is not None:
        doc.status = status
    elif doc.status in (
        DocStatus.processing,
        DocStatus.stitching,
        DocStatus.ocr_review,
        DocStatus.ready_for_chunking,
        DocStatus.failed,
    ):
        if any(p.status in PRE_REVIEW for p in pages):
            if doc.status != DocStatus.stitching:
                doc.status = DocStatus.processing
        elif pages and all(p.status == PageStatus.approved for p in pages):
            doc.status = DocStatus.ready_for_chunking
        elif any(p.status == PageStatus.review for p in pages):
            doc.status = DocStatus.ocr_review
        elif any(p.status == PageStatus.failed for p in pages):
            doc.status = DocStatus.failed
    return c.repo.save_doc(doc)


def maybe_stitch(c: Container, doc_id: str) -> bool:
    """Fan-in: khi mọi trang đã qua Docling/định tuyến/CU thì xếp job nối trang (một lần)."""
    pages = c.repo.list_pages(doc_id)
    if any(p.status in (PageStatus.queued, PageStatus.docling, PageStatus.routed, PageStatus.cu) for p in pages):
        return False
    if not any(p.status == PageStatus.ready for p in pages):
        return False
    job = enqueue(c, doc_id, "stitch", force=True)
    if job:
        refresh_doc(c, doc_id, DocStatus.stitching)
    return job is not None


def on_job_failed(c: Container, job: Job) -> None:
    if job.page:
        p = c.repo.get_page(job.doc_id, job.page)
        if p and p.status in PRE_REVIEW:
            p.status, p.error = PageStatus.failed, job.error[:300]
            c.repo.save_page(p)
    if job.step in ("chunk", "index", "stitch"):
        back = {"chunk": DocStatus.ready_for_chunking, "index": DocStatus.chunk_review, "stitch": DocStatus.failed}[
            job.step
        ]
        refresh_doc(c, job.doc_id, back)
    else:
        refresh_doc(c, job.doc_id)


# ================================================================== review OCR
def page_markdown(c: Container, p: Page) -> str:
    if p.current_version:
        return c.blob.get(k_version(p.doc_id, p.page, p.current_version)).decode()
    for name in ("stitched.md", "cu.md", "docling.md"):
        key = k_page(p.doc_id, p.page, name)
        if c.blob.exists(key):
            return c.blob.get(key).decode()
    return ""


def save_version(c: Container, p: Page, markdown: str, source: str, actor: str, note: str = "") -> Page:
    v = (max((x.v for x in p.versions), default=0)) + 1
    c.blob.put(k_version(p.doc_id, p.page, v), markdown.encode(), "text/markdown")
    p.versions.append(PageVersion(v=v, source=source, by=actor, at=now_iso(), note=note[:200]))
    p.current_version = v
    if p.status == PageStatus.approved and source != "stitched":
        p.status = PageStatus.review
        p.reviewed_by = p.reviewed_at = ""
    return c.repo.save_page(p)


def _require_reviewable(c: Container, doc_id: str, page: int) -> Page:
    p = c.repo.get_page(doc_id, page)
    if not p:
        raise PipelineError("page_not_found")
    doc = c.repo.get_doc(doc_id)
    if doc.status in (DocStatus.chunking, DocStatus.indexing):
        raise PipelineError("doc_busy")
    if p.status not in (PageStatus.review, PageStatus.approved):
        raise PipelineError("page_not_ready")
    return p


def edit_page(c: Container, doc_id: str, page: int, markdown: str, actor: str, note: str = "") -> Page:
    p = _require_reviewable(c, doc_id, page)
    p = save_version(c, p, markdown, "human", actor, note)
    emit(c, doc_id, "review.saved", page=page, v=p.current_version, by=actor)
    _invalidate_chunks(c, doc_id)
    refresh_doc(c, doc_id)
    return p


def submit_page(c: Container, doc_id: str, page: int, actor: str, markdown: str | None = None) -> Page:
    p = _require_reviewable(c, doc_id, page)
    if markdown is not None and markdown != page_markdown(c, p):
        p = save_version(c, p, markdown, "human", actor)
    p.status, p.reviewed_by, p.reviewed_at = PageStatus.approved, actor, now_iso()
    c.repo.save_page(p)
    emit(c, doc_id, "review.submitted", page=page, v=p.current_version, by=actor)
    c.repo.audit(actor, "page.submit", f"{doc_id}:{page}", v=p.current_version)
    doc = refresh_doc(c, doc_id)
    if doc.status == DocStatus.ready_for_chunking:
        emit(c, doc_id, "doc.ready_for_chunking")
    return p


def reopen_page(c: Container, doc_id: str, page: int, actor: str) -> Page:
    p = _require_reviewable(c, doc_id, page)
    p.status, p.reviewed_by, p.reviewed_at = PageStatus.review, "", ""
    c.repo.save_page(p)
    emit(c, doc_id, "review.reopened", page=page, by=actor)
    _invalidate_chunks(c, doc_id)
    refresh_doc(c, doc_id)
    return p


def restore_version(c: Container, doc_id: str, page: int, v: int, actor: str) -> Page:
    p = _require_reviewable(c, doc_id, page)
    if not any(x.v == v for x in p.versions):
        raise PipelineError("version_not_found")
    md = c.blob.get(k_version(doc_id, page, v)).decode()
    return edit_page(c, doc_id, page, md, actor, note=f"restore v{v}")


def rerun_page_llm(c: Container, doc_id: str, page: int, prompt: str, actor: str) -> Job | None:
    _require_reviewable(c, doc_id, page)
    if not c.config.is_configured("llm"):
        raise PipelineError("llm_not_configured")
    return enqueue(c, doc_id, "rerun", page, {"prompt": prompt[:2000]}, actor=actor)


def set_route_override(c: Container, doc_id: str, page: int, override: str, actor: str) -> Page:
    p = c.repo.get_page(doc_id, page)
    if not p:
        raise PipelineError("page_not_found")
    if override not in ("auto", "force_cu", "skip_cu"):
        raise PipelineError("bad_override")
    p.route_override = override
    if p.status not in (PageStatus.docling, PageStatus.queued):
        p.status = PageStatus.routed
    c.repo.save_page(p)
    c.repo.audit(actor, "page.route_override", f"{doc_id}:{page}", override=override)
    if p.engine:
        enqueue(c, doc_id, "route", page, actor=actor)
    refresh_doc(c, doc_id)
    return p


def reprocess_page(c: Container, doc_id: str, page: int, actor: str) -> Page:
    p = c.repo.get_page(doc_id, page)
    if not p:
        raise PipelineError("page_not_found")
    p.status, p.error = PageStatus.queued, ""
    c.repo.save_page(p)
    enqueue(c, doc_id, "docling", page, actor=actor)
    refresh_doc(c, doc_id)
    return p


def _invalidate_chunks(c: Container, doc_id: str) -> None:
    doc = c.repo.get_doc(doc_id)
    if doc.status in (DocStatus.chunk_review, DocStatus.indexed):
        emit(c, doc_id, "chunk.invalidated", "warn")
        refresh_doc(c, doc, DocStatus.ocr_review)


# ================================================================== tự duyệt (UI v2, chỉ tài liệu auto_review)
AUTO = "auto"  # người duyệt của luồng tự động


def auto_approve_pages(c: Container, doc_id: str) -> int:
    """Duyệt mọi trang đang chờ review với người duyệt "auto". Chỉ gọi cho tài liệu `auto_review`."""
    n = 0
    for p in c.repo.list_pages(doc_id):
        if p.status == PageStatus.review:
            p.status, p.reviewed_by, p.reviewed_at = PageStatus.approved, AUTO, now_iso()
            c.repo.save_page(p)
            n += 1
    if n:
        emit(c, doc_id, "auto.pages_approved", count=n)
    refresh_doc(c, doc_id)
    return n


def approve_all_pages(c: Container, doc_id: str, actor: str) -> Job | None:
    """「すべて承認」 ở OCR レビュー (đã xác nhận): duyệt mọi trang còn chờ với người duyệt là người bấm, rồi chuyển
    luôn sang chunk. Trang đang xử lý / lỗi thì không duyệt được."""
    doc = c.repo.get_doc(doc_id)
    if not doc or doc.status not in (DocStatus.ocr_review, DocStatus.ready_for_chunking):
        raise PipelineError("doc_not_in_ocr_review")
    pages = c.repo.list_pages(doc_id)
    if any(p.status not in (PageStatus.review, PageStatus.approved) for p in pages):
        raise PipelineError("pages_not_ready")
    n = 0
    for p in pages:
        if p.status == PageStatus.review:
            p.status, p.reviewed_by, p.reviewed_at = PageStatus.approved, actor, now_iso()
            c.repo.save_page(p)
            n += 1
    emit(c, doc_id, "review.approved_all", count=n, by=actor)
    c.repo.audit(actor, "review.approve_all", doc_id, pages=n)
    refresh_doc(c, doc_id)
    return start_chunking(c, doc_id, actor)


def approve_all_chunks(c: Container, doc_id: str, actor: str) -> Job | None:
    """「すべて承認」 ở チャンクレビュー (đã xác nhận): duyệt mọi chunk nháp (người bấm = người duyệt) rồi index."""
    doc = c.repo.get_doc(doc_id)
    if not doc or doc.status != DocStatus.chunk_review:
        raise PipelineError("doc_not_in_chunk_review")
    n = 0
    for x in c.repo.list_chunks(doc_id):
        if x.status == ChunkStatus.draft:
            x.status, x.edited_by = ChunkStatus.approved, actor
            c.repo.save_chunk(x)
            n += 1
    emit(c, doc_id, "chunk.approved_all", count=n, by=actor)
    c.repo.audit(actor, "chunk.approve_all", doc_id, chunks=n)
    refresh_doc(c, doc_id)
    return start_index(c, doc_id, actor)


def auto_approve_chunks(c: Container, doc_id: str) -> int:
    n = 0
    for x in c.repo.list_chunks(doc_id):
        if x.status == ChunkStatus.draft:
            x.status, x.edited_by = ChunkStatus.approved, AUTO
            c.repo.save_chunk(x)
            n += 1
    emit(c, doc_id, "auto.chunks_approved", count=n)
    return n


def auto_start_index(c: Container, doc_id: str) -> Job | None:
    """Sau khi chunk xong (tài liệu auto_review): tự duyệt chunk rồi xếp job index. Không kiểm tra cấu hình
    trước — thiếu embedding/search thì job index bị chặn (failed, có Retry) để thẻ nguồn hiện lỗi."""
    auto_approve_chunks(c, doc_id)
    if not c.repo.list_chunks(doc_id):
        emit(c, doc_id, "auto.no_chunks", "warn")
        refresh_doc(c, doc_id, DocStatus.indexed)
        return None
    job = enqueue(c, doc_id, "index", actor=AUTO)
    if job:
        refresh_doc(c, doc_id, DocStatus.indexing)
    return job


# ================================================================== chunk & index
def start_chunking(c: Container, doc_id: str, actor: str, book_pages: list[int] | None = None) -> Job | None:
    """`book_pages`: chỉ các trang sách này vừa đổi nội dung → bước chunk chỉ chunk lại các mục liên quan."""
    doc = c.repo.get_doc(doc_id)
    pages = c.repo.list_pages(doc_id)
    if not pages or any(p.status != PageStatus.approved for p in pages):
        raise PipelineError("pages_not_approved")
    job = enqueue(c, doc_id, "chunk", params={"pages": sorted(book_pages)} if book_pages else None, actor=actor)
    if job:
        refresh_doc(c, doc, DocStatus.chunking)
    return job


def start_index(c: Container, doc_id: str, actor: str) -> Job | None:
    doc = c.repo.get_doc(doc_id)
    chunks = c.repo.list_chunks(doc_id)
    if not chunks or any(x.status == ChunkStatus.draft for x in chunks):
        raise PipelineError("chunks_not_approved")
    for comp in ("embedding", "search"):
        if not c.config.is_configured(comp):
            raise PipelineError(f"{comp}_not_configured")
    job = enqueue(c, doc_id, "index", actor=actor)
    if job:
        refresh_doc(c, doc, DocStatus.indexing)
    return job


def set_enabled(c: Container, doc_id: str, enabled: bool, actor: str) -> Document:
    doc = c.repo.get_doc(doc_id)
    doc.enabled = enabled
    c.repo.save_doc(doc)
    if c.config.is_configured("search"):
        c.config.adapter("search").set_enabled(doc_id, enabled)
    c.repo.audit(actor, "document.enabled", doc_id, enabled=enabled)
    return doc


def delete_document(c: Container, doc_id: str, actor: str) -> None:
    for j in c.repo.list_jobs({"doc_id": doc_id}):
        if j.status in (JobStatus.queued, JobStatus.running):
            raise PipelineError("doc_busy")
    if c.config.is_configured("search"):
        try:
            c.config.adapter("search").delete_doc(doc_id)
        except Exception:  # noqa: BLE001 — index chưa tồn tại
            pass
    c.blob.delete_prefix(f"docs/{doc_id}")
    c.repo.delete_doc(doc_id)
    c.repo.audit(actor, "document.delete", doc_id)
