"""Model nghiệp vụ. Lưu dưới dạng document (dict) trong DocStore, partition theo doc_id hoặc "_" (global).

Quy ước collection → partition:
  documents, users, jobs, audit, settings, secrets  → "_"
  pages, versions, chunks, events                    → doc_id
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

GLOBAL = "_"


class Role(StrEnum):
    admin = "admin"
    reviewer = "reviewer"
    viewer = "viewer"


ROLE_RANK = {Role.viewer: 0, Role.reviewer: 1, Role.admin: 2}


class User(BaseModel):
    id: str
    email: str
    name: str = ""
    role: Role = Role.viewer
    password_hash: str = ""
    provider: str = "local"  # local | google | entra
    active: bool = True
    created_at: str = ""
    last_login_at: str = ""

    def public(self) -> dict:
        return self.model_dump(exclude={"password_hash"})


# ------------------------------------------------------------------ tài liệu & trang
class DocStatus(StrEnum):
    processing = "processing"  # Docling / định tuyến / CU đang chạy
    stitching = "stitching"
    ocr_review = "ocr_review"  # chờ người review OCR
    ready_for_chunking = "ready_for_chunking"  # mọi trang đã Submit
    chunking = "chunking"
    chunk_review = "chunk_review"
    indexing = "indexing"
    indexed = "indexed"
    failed = "failed"


class Document(BaseModel):
    id: str
    name: str
    kind: str = ""  # akahon (赤本) | midorihon (緑本) | other
    filename: str = ""
    book_page_start: int = 1  # số trang in trong sách của trang PDF đầu tiên được xử lý
    page_from: int = 1  # dải trang PDF được xử lý (1-based, gồm cả 2 đầu)
    page_to: int = 1
    total_pdf_pages: int = 0
    enabled: bool = True
    status: DocStatus = DocStatus.processing
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""
    config_version: int = 0  # phiên bản tuỳ chọn pipeline lúc upload
    stats: dict[str, int] = Field(default_factory=dict)
    auto_review: bool = False  # review.auto_review lúc upload: tự duyệt trang/chunk, điểm yếu chuyển cho người xử lý
    file_type: str = "pdf"  # pdf | image (ảnh được đổi sang PDF 1 trang khi tải lên)
    size_bytes: int = 0

    @property
    def n_pages(self) -> int:
        return self.page_to - self.page_from + 1

    def book_page(self, pdf_page: int) -> int:
        return self.book_page_start + (pdf_page - self.page_from)


class PageStatus(StrEnum):
    queued = "queued"
    docling = "docling"  # đang chạy Docling
    routed = "routed"
    cu = "cu"  # đang chạy CU
    ready = "ready"  # chờ nối trang
    review = "review"  # chờ người review
    approved = "approved"  # đã Submit
    failed = "failed"


class PageScores(BaseModel):
    """Điểm Docling của trang (conv_res.confidence.pages[page_no]). None = không có."""

    parse_score: float | None = None
    layout_score: float | None = None
    ocr_score: float | None = None
    table_score: float | None = None
    mean_score: float | None = None
    low_score: float | None = None
    mean_grade: str = "unspecified"
    low_grade: str = "unspecified"


class PageFeatures(BaseModel):
    has_text_layer: bool = True
    n_tables: int = 0
    complex_tables: int = 0  # bảng có ô gộp
    table_at_bottom: bool = False  # bảng chạm cuối trang → có thể tràn sang trang sau
    table_at_top: bool = False
    n_figures: int = 0
    max_figure_area: float = 0.0  # tỉ lệ diện tích hình lớn nhất / trang
    removed: dict[str, int] = Field(default_factory=dict)  # logo / stamp / signature → số lượng


class PageVersion(BaseModel):
    v: int
    source: str  # stitched | human | llm
    by: str = ""
    at: str = ""
    note: str = ""


class Page(BaseModel):
    id: str  # "{page:04d}"
    doc_id: str
    page: int
    book_page: int
    status: PageStatus = PageStatus.queued
    engine: str = ""  # docling | pdfium
    scores: PageScores = Field(default_factory=PageScores)
    features: PageFeatures = Field(default_factory=PageFeatures)
    route: Literal["easy", "hard"] | None = None
    route_reasons: list[str] = Field(default_factory=list)
    route_override: Literal["auto", "force_cu", "skip_cu"] = "auto"
    cu_status: str = ""  # "" | done | skipped | failed
    continues_next: bool = False  # đoạn cuối trang nối sang trang sau
    table_continues_next: bool = False
    current_version: int = 0
    versions: list[PageVersion] = Field(default_factory=list)
    reviewed_by: str = ""
    reviewed_at: str = ""
    updated_at: str = ""
    error: str = ""


def page_key(page: int) -> str:
    return f"{page:04d}"


# ------------------------------------------------------------------ chunk
class ChunkStatus(StrEnum):
    draft = "draft"
    approved = "approved"
    indexed = "indexed"


class Chunk(BaseModel):
    id: str
    doc_id: str
    seq: int
    item_code: str = ""
    title: str = ""
    text: str
    page_from: int  # trang trong sách
    page_to: int
    confidence: float = 0.0
    rule_score: float = 0.0
    llm_score: float | None = None
    violations: list[str] = Field(default_factory=list)
    rounds: int = 0
    status: ChunkStatus = ChunkStatus.draft
    edited_by: str = ""
    updated_at: str = ""
    # Khoá mục (section) sinh ra chunk, vd "M017#0" — để chunk lại riêng phần bị sửa, giữ chunk khác (kể cả sửa tay).
    # Gộp chunk → hợp các khoá. Rỗng = chunk cũ trước khi có trường này → lần sau chunk lại toàn bộ.
    sections: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ job & live log
class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class Job(BaseModel):
    id: str  # "{doc_id}:{step}:{page|-}" — khoá idempotent
    doc_id: str
    step: str
    queue: str
    page: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)  # không chứa nội dung tài liệu
    status: JobStatus = JobStatus.queued
    attempts: int = 0
    max_attempts: int = 3
    config_version: int = 0
    error: str = ""
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    updated_at: str = ""
    created_by: str = ""


class JobEvent(BaseModel):
    """Một dòng live log. Chỉ có mã + tham số (id, trang, số đếm, lý do), không có nội dung tài liệu."""

    id: str
    doc_id: str
    job_id: str = ""
    step: str = ""
    page: int | None = None
    level: Literal["debug", "info", "warn", "error"] = "info"
    code: str
    params: dict[str, Any] = Field(default_factory=dict)
    ts: str = ""


class AuditEntry(BaseModel):
    id: str
    actor: str
    action: str
    target: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    at: str = ""
