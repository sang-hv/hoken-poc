"""Pipeline tự chạy hết (review.auto_review): upload ở màn 文書 → OCR → tự duyệt → chunk → tự duyệt → index;
ảnh → PDF 1 trang; sửa phần tử → chunk + index lại."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

import app.steps.handlers  # noqa: F401 — đăng ký step
from app.adapters.memory import HashEmbedder, MemorySearch
from app.domain.models import ChunkStatus, DocStatus, Document, PageStatus
from app.services import inspect as inspect_svc
from app.services import pipeline as pl
from app.services.jobs import run_worker

H = {"X-Requested-With": "hoken"}
QUEUES = ["docling", "light", "ai"]


def drain(c):
    return run_worker(c, QUEUES, drain=True, idle_exit_s=0, poll_s=0)


def _search_ready(c):
    c.config.overrides.update({"embedding": HashEmbedder(32), "search": MemorySearch()})


@pytest.fixture
def client(container):
    from app.api.server import create_app

    with TestClient(create_app()) as cl:
        r = cl.post("/api/setup", json={"email": "admin@example.com", "password": "password-123"}, headers=H)
        assert r.status_code == 200, r.text
        yield cl


def _png(size=(300, 200)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _auto_doc(c, pdf: bytes) -> Document:
    return pl.create_document(
        c,
        data=pdf,
        filename="s.pdf",
        name="Sample",
        kind="other",
        book_page_start=1,
        page_from=None,
        page_to=None,
        actor="u1",
        auto_review=True,
    )


def test_upload_runs_whole_pipeline_with_auto_review(client, container, sample_pdf, monkeypatch):
    c = container
    _search_ready(c)
    prepared = []
    monkeypatch.setattr(inspect_svc, "prepare_document", lambda c_, doc_id: prepared.append(doc_id))
    r = client.post(
        "/api/documents", files={"file": ("s.pdf", sample_pdf, "application/pdf")}, data={"name": "S"}, headers=H
    )
    assert r.status_code == 200, r.text
    doc = c.repo.get_doc(r.json()["id"])
    assert doc.auto_review and doc.file_type == "pdf" and doc.size_bytes == len(sample_pdf)

    drain(c)
    assert c.repo.get_doc(doc.id).status == DocStatus.indexed
    assert prepared == [doc.id]
    assert all(p.status == PageStatus.approved and p.reviewed_by == "auto" for p in c.repo.list_pages(doc.id))
    chunks = c.repo.list_chunks(doc.id)
    assert chunks and all(x.status == ChunkStatus.indexed and x.edited_by == "auto" for x in chunks)
    codes = {e.code for e in c.repo.recent_events(doc.id, limit=1000)}
    assert {"auto.pages_approved", "auto.chunks_approved", "index.done"} <= codes
    assert c.config.overrides["search"].count() == len(chunks)


def test_prepare_failure_does_not_block(container, sample_pdf, monkeypatch):
    c = container

    def boom(c_, doc_id):
        raise RuntimeError("x")

    monkeypatch.setattr(inspect_svc, "prepare_document", boom)
    doc = _auto_doc(c, sample_pdf)
    drain(c)  # chưa cấu hình embedding/search → job index bị chặn, nhưng chunk vẫn được tự duyệt
    codes = {e.code for e in c.repo.recent_events(doc.id, limit=1000)}
    assert "auto.prepare_failed" in codes and "auto.chunks_approved" in codes


def test_image_upload_becomes_one_page_pdf(client, container):
    c = container
    _search_ready(c)
    png = _png()
    r = client.post("/api/documents", files={"file": ("scan.png", png, "image/png")}, headers=H)
    assert r.status_code == 200, r.text
    doc = c.repo.get_doc(r.json()["id"])
    assert doc.file_type == "image" and doc.n_pages == 1 and doc.size_bytes == len(png) and doc.filename == "scan.png"
    assert client.get(f"/api/documents/{doc.id}/source").content.startswith(b"%PDF")
    drain(c)  # ảnh trắng → không có chữ → không có chunk → vẫn xong
    assert c.repo.get_doc(doc.id).status == DocStatus.indexed

    bad = client.post("/api/documents", files={"file": ("a.txt", b"hello", "text/plain")}, headers=H)
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "unsupported_file"
    from PIL import Image

    jpg = io.BytesIO()
    Image.new("RGB", (120, 80)).save(jpg, format="JPEG")
    pdf, kind = pl.to_pdf(jpg.getvalue())
    assert kind == "image" and pdf.startswith(b"%PDF")


def test_manual_review_documents_unaffected(container, sample_pdf):
    c = container
    _search_ready(c)
    doc = pl.create_document(
        c,
        data=sample_pdf,
        filename="s.pdf",
        name="Manual",
        kind="akahon",
        book_page_start=536,
        page_from=None,
        page_to=None,
        actor="u1",
    )
    drain(c)
    doc = c.repo.get_doc(doc.id)
    assert not doc.auto_review and doc.status == DocStatus.ocr_review
    assert all(p.status == PageStatus.review and not p.reviewed_by for p in c.repo.list_pages(doc.id))
    assert not any(j.step == "auto_review" for j in c.repo.list_jobs({"doc_id": doc.id}))
    inspect_svc.reindex_document(c, doc.id, "u1")  # không phải auto_review → không làm gì
    assert c.repo.get_doc(doc.id).status == DocStatus.ocr_review


def test_reindex_after_edit(container, sample_pdf):
    c = container
    _search_ready(c)
    doc = _auto_doc(c, sample_pdf)
    drain(c)
    p = c.repo.list_pages(doc.id)[0]
    pl.edit_page(c, doc.id, p.page, pl.page_markdown(c, p) + "\nZ999 Added item 50 points.\n", "u1")
    assert c.repo.get_page(doc.id, p.page).status == PageStatus.review
    inspect_svc.reindex_document(c, doc.id, "u1")
    drain(c)
    assert c.repo.get_doc(doc.id).status == DocStatus.indexed
    assert c.repo.get_page(doc.id, p.page).reviewed_by == "auto"
    assert any("Z999" in x.text for x in c.repo.list_chunks(doc.id))


def test_edit_while_indexing_is_deferred_then_reindexed(container, monkeypatch):
    """Sửa phần tử khi tài liệu đang chunk/index: không chặn, ghi cờ, index xong thì chạy lại."""
    c = container
    c.repo.save_doc(Document(id="d1", name="x", auto_review=True, status=DocStatus.indexing))
    inspect_svc.reindex_document(c, "d1", "u1")
    assert c.repo.s.get(inspect_svc.FLAGS, "d1", "reindex_pending")["by"] == "u1"
    called = []
    monkeypatch.setattr(inspect_svc, "reindex_document", lambda c_, d, a: called.append((d, a)))
    inspect_svc.run_pending_reindex(c, "d1")
    inspect_svc.run_pending_reindex(c, "d1")  # cờ đã xoá → không chạy lại lần 2
    assert called == [("d1", "u1")]


def test_chunk_edit_on_auto_doc_reindexes(container, sample_pdf):
    """Tab チャンク: sửa / tách chunk của tài liệu tự chạy → duyệt luôn (người sửa) rồi index lại."""
    from app.services import chunks as chunk_svc

    c = container
    _search_ready(c)
    doc = _auto_doc(c, sample_pdf)
    drain(c)
    first = c.repo.list_chunks(doc.id)[0]
    chunk_svc.update_chunk(
        c,
        doc.id,
        first.id,
        text=first.text + "\nZ777 追記",
        item_code=first.item_code,
        title=first.title,
        page_from=None,
        page_to=None,
        actor="u1",
    )
    assert c.repo.get_doc(doc.id).status == DocStatus.indexing
    drain(c)
    assert c.repo.get_doc(doc.id).status == DocStatus.indexed
    edited = c.repo.get_chunk(doc.id, first.id)
    assert edited.status == ChunkStatus.indexed and edited.edited_by == "u1" and "Z777" in edited.text
    n = len(c.repo.list_chunks(doc.id))
    chunk_svc.split_chunk(c, doc.id, first.id, len(first.text) // 2, "u1")
    drain(c)
    assert len(c.repo.list_chunks(doc.id)) == n + 1 and c.repo.get_doc(doc.id).status == DocStatus.indexed
    assert c.config.overrides["search"].count() == n + 1
