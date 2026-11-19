"""Chạy cả luồng khu A với adapter in-memory: upload → docling → định tuyến → nối trang → review → chunk → index."""

from __future__ import annotations

import json

import app.steps.handlers  # noqa: F401 — đăng ký step
from app.adapters.memory import FakeLayout, HashEmbedder, MemorySearch, ScriptedLLM
from app.domain.models import ChunkStatus, DocStatus, JobStatus, PageStatus
from app.services import chunks as chunk_svc
from app.services import pipeline as pl
from app.services.jobs import run_worker

QUEUES = ["docling", "light", "ai"]


def drain(c):
    return run_worker(c, QUEUES, drain=True, idle_exit_s=0, poll_s=0)


def test_full_flow_without_ai(container, sample_pdf):
    c = container
    doc = pl.create_document(
        c,
        data=sample_pdf,
        filename="s.pdf",
        name="Sample",
        kind="akahon",
        book_page_start=536,
        page_from=None,
        page_to=None,
        actor="u1",
    )
    drain(c)
    doc = c.repo.get_doc(doc.id)
    pages = c.repo.list_pages(doc.id)
    assert [p.book_page for p in pages] == [536, 537, 538]
    # Không có Docling trong môi trường test → engine pdfium → hard (no_docling); CU chưa cấu hình → skipped
    assert all(p.engine == "pdfium" and "no_docling" in p.route_reasons for p in pages)
    assert all(p.cu_status == "skipped" and p.status == PageStatus.review for p in pages)
    assert doc.status == DocStatus.ocr_review

    # Header lặp lại và số trang bị bỏ khi nối trang
    md = pl.page_markdown(c, pages[0])
    assert "Dental fee schedule header" not in md
    assert pages[0].current_version == 1 and pages[0].versions[0].source == "stitched"

    # Review: sửa trang 1 rồi Submit tất cả
    pl.edit_page(c, doc.id, pages[0].page, md + "\nEdited line.\n", "u1")
    for p in pages:
        pl.submit_page(c, doc.id, p.page, "u1")
    assert c.repo.get_doc(doc.id).status == DocStatus.ready_for_chunking

    # Chunk không dùng LLM
    c.config.overrides["llm"] = None
    del c.config.overrides["llm"]
    pl.start_chunking(c, doc.id, "u1")
    drain(c)
    doc = c.repo.get_doc(doc.id)
    assert doc.status == DocStatus.chunk_review
    chunks = c.repo.list_chunks(doc.id)
    codes = [x.item_code for x in chunks]
    assert "M015-2" in codes and "M016" in codes and "A000" in codes

    # Chưa duyệt chunk thì không index được
    c.config.overrides.update({"embedding": HashEmbedder(32), "search": MemorySearch()})
    try:
        pl.start_index(c, doc.id, "u1")
        raise AssertionError("phải lỗi")
    except pl.PipelineError as e:
        assert e.code == "chunks_not_approved"
    chunk_svc.approve_chunks(c, doc.id, [x.id for x in chunks], True, "u1")
    pl.start_index(c, doc.id, "u1")
    drain(c)
    assert c.repo.get_doc(doc.id).status == DocStatus.indexed
    assert all(x.status == ChunkStatus.indexed for x in c.repo.list_chunks(doc.id))
    search = c.config.overrides["search"]
    hits = search.search("M016 Metal crown", HashEmbedder(32).embed(["M016 Metal crown"])[0], 3)
    assert hits and hits[0].item_code == "M016"

    # Live log có đủ các bước, không có nội dung tài liệu
    evs = c.repo.recent_events(doc.id, limit=1000)
    codes_seen = {e.code for e in evs}
    assert {
        "docling.done",
        "route.decided",
        "cu.not_configured",
        "stitch.done",
        "review.submitted",
        "chunk.done",
        "index.done",
    } <= codes_seen
    assert not any("crown" in str(e.params).lower() for e in evs)


def test_cu_and_llm_chunk_loop(container, sample_pdf):
    c = container
    c.config.overrides["cu"] = FakeLayout("M015-2 CAD/CAM crown\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    calls = {"n": 0}

    def responder(messages, tier, json_mode):
        if tier == "mini":
            return '{"score": 0.9}'
        calls["n"] += 1
        user = messages[-1].text
        last = int(user.split("Lines 0..")[1].split(":")[0])
        if calls["n"] == 1:  # vòng đầu cố tình thiếu dòng → validator bắt lỗi coverage
            return '{"chunks": [{"start": 0, "end": 0, "item_code": "X"}]}'
        return json.dumps({"chunks": [{"start": 0, "end": last, "item_code": "OK"}]})

    c.config.overrides["llm"] = ScriptedLLM(responder)
    doc = pl.create_document(
        c,
        data=sample_pdf,
        filename="s.pdf",
        name="S",
        kind="akahon",
        book_page_start=1,
        page_from=1,
        page_to=1,
        actor="u1",
    )
    drain(c)
    p = c.repo.list_pages(doc.id)[0]
    assert p.cu_status == "done"
    assert "| a | b |" in pl.page_markdown(c, p)
    pl.submit_page(c, doc.id, 1, "u1")
    pl.start_chunking(c, doc.id, "u1")
    drain(c)
    chunks = c.repo.list_chunks(doc.id)
    assert chunks and chunks[0].rounds == 2 and chunks[0].llm_score == 0.9
    rounds = [e for e in c.repo.recent_events(doc.id, 1000) if e.code == "chunk.round"]
    assert rounds[0].params["violations"] > 0 and rounds[-1].params["violations"] == 0


def test_job_retry_then_fail_and_dedupe(container, sample_pdf, monkeypatch):
    c = container
    from app.services import jobs

    doc = pl.create_document(
        c, data=sample_pdf, filename="s.pdf", name="S", kind="", book_page_start=1, page_from=1, page_to=1, actor="u1"
    )
    # Job đang queued → enqueue lần nữa không tạo bản trùng
    assert jobs.enqueue(c, doc.id, "docling", 1) is None

    def boom(ctx):
        raise RuntimeError("x")

    monkeypatch.setitem(jobs.STEPS, "docling", jobs.StepDef("docling", boom, 2))
    for _ in range(4):
        for m in c.queue.receive("docling", 5, 0):
            jobs.process_message(c, "docling", m)
        for it in c.queue.items.get("docling", []):
            it["visible"] = 0
    j = c.repo.get_job(jobs.job_id(doc.id, "docling", 1))
    assert j.status == JobStatus.failed and j.attempts == 3
    assert c.repo.get_page(doc.id, 1).status == PageStatus.failed
