"""UI v2 — Sổ tay: CRUD, upload tự chạy hết pipeline (tự duyệt "auto"), ảnh → PDF, chat Agentic RAG."""

from __future__ import annotations

import io
import json

import pytest
from conftest import make_pdf
from fastapi.testclient import TestClient

import app.steps.handlers  # noqa: F401 — đăng ký step
from app.adapters.memory import HashEmbedder, MemorySearch, ScriptedLLM
from app.domain.models import ChunkStatus, DocStatus, Document, PageStatus
from app.ports import ChatResult
from app.services import inspect as inspect_svc
from app.services import notebooks as nbs
from app.services import pipeline as pl
from app.services.jobs import run_worker
from scripts.demo import mock_notebook

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


def _nb_with_doc(c, pdf: bytes, name: str = "Sample") -> tuple[dict, dict]:
    nb = nbs.create_notebook(c, f"NB {name}", "u1")
    src = nbs.add_source(c, nb, data=pdf, filename=f"{name}.pdf", name=name, actor="u1")
    return nb, src


# ================================================================== CRUD + quyền
def test_notebook_crud_and_roles(client, container):
    r = client.post("/api/notebooks", json={"name": "  My notebook "}, headers=H)
    assert r.status_code == 200, r.text
    nb = r.json()
    assert nb["name"] == "My notebook" and nb["source_count"] == 0 and nb["note_count"] == 0
    assert nb["created_by"] == "admin@example.com"
    assert [x["id"] for x in client.get("/api/notebooks").json()] == [nb["id"]]

    r = client.patch(f"/api/notebooks/{nb['id']}", json={"name": "Renamed"}, headers=H)
    assert r.json()["name"] == "Renamed"

    note = client.post(f"/api/notebooks/{nb['id']}/notes", json={"title": "T", "text": "hello"}, headers=H).json()
    assert set(note) == {"id", "title", "text", "created_by", "created_at", "updated_at"}
    r = client.patch(f"/api/notebooks/{nb['id']}/notes/{note['id']}", json={"text": "updated"}, headers=H)
    assert r.json()["text"] == "updated" and r.json()["title"] == "T"
    d = client.get(f"/api/notebooks/{nb['id']}").json()
    assert d["note_count"] == 1 and d["notes"][0]["text"] == "updated" and d["sources"] == []

    assert client.get("/api/notebooks/nope").status_code == 404
    assert client.get("/api/notebooks/nope").json()["detail"]["code"] == "notebook_not_found"
    r = client.patch(f"/api/notebooks/{nb['id']}/notes/nope", json={"text": "x"}, headers=H)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "note_not_found"
    r = client.patch(f"/api/notebooks/{nb['id']}/sources/nope", json={"enabled": False}, headers=H)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "source_not_found"

    # viewer: xem được, không sửa / chat được
    client.post("/api/users", json={"email": "v@example.com", "role": "viewer", "password": "password-123"}, headers=H)
    client.post("/api/auth/logout", headers=H)
    client.post("/api/auth/login", json={"email": "v@example.com", "password": "password-123"}, headers=H)
    assert client.get(f"/api/notebooks/{nb['id']}").status_code == 200
    assert client.post("/api/notebooks", json={"name": "x"}, headers=H).status_code == 403
    assert client.post(f"/api/notebooks/{nb['id']}/chat", json={"q": "hi"}, headers=H).status_code == 403
    client.post("/api/auth/logout", headers=H)
    client.post("/api/auth/login", json={"email": "admin@example.com", "password": "password-123"}, headers=H)

    assert client.delete(f"/api/notebooks/{nb['id']}/notes/{note['id']}", headers=H).json() == {"ok": True}
    assert client.delete(f"/api/notebooks/{nb['id']}", headers=H).json() == {"ok": True}
    assert client.get("/api/notebooks").json() == []


# ================================================================== upload → pipeline tự động
def test_upload_runs_whole_pipeline_with_auto_review(client, container, sample_pdf, monkeypatch):
    c = container
    _search_ready(c)
    prepared = []
    monkeypatch.setattr(inspect_svc, "prepare_document", lambda c_, doc_id: prepared.append(doc_id))
    nb = client.post("/api/notebooks", json={"name": "NB"}, headers=H).json()
    r = client.post(
        f"/api/notebooks/{nb['id']}/sources",
        files={"file": ("s.pdf", sample_pdf, "application/pdf")},
        data={"name": "Sample"},
        headers=H,
    )
    assert r.status_code == 200, r.text
    src = r.json()
    assert src["stage"] in ("upload", "docling") and src["file_type"] == "pdf" and src["enabled"] is True
    assert src["pages"] == 3 and src["quality"] is None
    doc = c.repo.get_doc(src["doc_id"])
    assert doc.auto_review and doc.size_bytes == len(sample_pdf) and (doc.page_from, doc.page_to) == (1, 3)

    drain(c)
    d = client.get(f"/api/notebooks/{nb['id']}").json()
    s = d["sources"][0]
    assert d["source_count"] == 1
    assert (s["status"], s["stage"], s["progress"], s["error"]) == ("indexed", "done", 100, "")
    assert prepared == [doc.id]
    pages = c.repo.list_pages(doc.id)
    assert all(p.status == PageStatus.approved and p.reviewed_by == "auto" for p in pages)
    chunks = c.repo.list_chunks(doc.id)
    assert chunks and all(x.status == ChunkStatus.indexed and x.edited_by == "auto" for x in chunks)
    codes = {e.code for e in c.repo.recent_events(doc.id, limit=1000)}
    assert {"auto.pages_approved", "auto.chunks_approved", "index.done"} <= codes
    assert c.config.overrides["search"].count() == len(chunks)

    # Tắt nguồn → chỉ đổi cờ trong sổ tay; xoá nguồn → xoá luôn tài liệu
    r = client.patch(f"/api/notebooks/{nb['id']}/sources/{doc.id}", json={"enabled": False}, headers=H)
    assert r.json()["enabled"] is False
    assert client.delete(f"/api/notebooks/{nb['id']}/sources/{doc.id}", headers=H).json() == {"ok": True}
    assert c.repo.get_doc(doc.id) is None and client.get(f"/api/notebooks/{nb['id']}").json()["sources"] == []


def test_prepare_failure_does_not_block_and_missing_index_shows_failed(container, sample_pdf, monkeypatch):
    c = container

    def boom(c_, doc_id):
        raise RuntimeError("x")

    monkeypatch.setattr(inspect_svc, "prepare_document", boom)
    nb, src = _nb_with_doc(c, sample_pdf)
    drain(c)  # chưa cấu hình embedding/search → job index bị chặn
    s = nbs.detail(c, nb)["sources"][0]
    assert s["stage"] == "failed" and s["error"] == "embedding_not_configured"
    codes = {e.code for e in c.repo.recent_events(src["doc_id"], limit=1000)}
    assert "auto.prepare_failed" in codes and "auto.chunks_approved" in codes


def test_image_upload_becomes_one_page_pdf(client, container):
    c = container
    _search_ready(c)
    png = _png()
    nb = client.post("/api/notebooks", json={"name": "NB"}, headers=H).json()
    r = client.post(f"/api/notebooks/{nb['id']}/sources", files={"file": ("scan.png", png, "image/png")}, headers=H)
    assert r.status_code == 200, r.text
    src = r.json()
    assert src["file_type"] == "image" and src["pages"] == 1 and src["name"] == "scan.png"
    doc = c.repo.get_doc(src["doc_id"])
    assert doc.size_bytes == len(png) and doc.filename == "scan.png"
    assert client.get(f"/api/documents/{doc.id}/source").content.startswith(b"%PDF")
    drain(c)  # ảnh trắng → không có chữ → không có chunk → vẫn xong
    assert nbs.detail(c, nb)["sources"][0]["stage"] == "done"

    bad = client.post(
        f"/api/notebooks/{nb['id']}/sources", files={"file": ("a.txt", b"hello", "text/plain")}, headers=H
    )
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "unsupported_file"
    jpg = io.BytesIO()
    from PIL import Image

    Image.new("RGB", (120, 80)).save(jpg, format="JPEG")
    pdf, kind = nbs.to_pdf(jpg.getvalue())
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
    nbs.reindex_document(c, doc.id, "u1")  # không phải auto_review → không làm gì
    assert c.repo.get_doc(doc.id).status == DocStatus.ocr_review


def test_reindex_after_edit(container, sample_pdf):
    c = container
    _search_ready(c)
    nb, src = _nb_with_doc(c, sample_pdf)
    drain(c)
    doc_id = src["doc_id"]
    p = c.repo.list_pages(doc_id)[0]
    pl.edit_page(c, doc_id, p.page, pl.page_markdown(c, p) + "\nZ999 Added item 50 points.\n", "u1")
    assert c.repo.get_page(doc_id, p.page).status == PageStatus.review
    nbs.reindex_document(c, doc_id, "u1")
    drain(c)
    assert c.repo.get_doc(doc_id).status == DocStatus.indexed
    assert c.repo.get_page(doc_id, p.page).reviewed_by == "auto"
    assert any("Z999" in x.text for x in c.repo.list_chunks(doc_id))


# ================================================================== hàm thuần
def test_pure_helpers():
    d = Document(id="d", name="n", book_page_start=536, page_from=2, page_to=4)
    assert [nbs.book_to_pdf(d, b) for b in (536, 537, 538, 999, 1)] == [2, 3, 4, 4, 2]

    assert nbs.parse_action('{"action":"search","query":" M016 "}') == {"action": "search", "query": "M016"}
    a = nbs.parse_action(json.dumps({"action": "answer", "answer": "800 [2]", "cited": [1, "x"], "handoff": False}))
    assert a == {"action": "answer", "answer": "800 [2]", "cited": [1, 2], "handoff": False}
    assert nbs.parse_action('{"action":"answer","answer":""}')["handoff"] is True
    assert nbs.parse_action("plain [3]")["cited"] == [3]
    assert nbs.parse_action('{"action":"search","query":""}')["action"] == "answer"

    S = PageStatus
    assert nbs.source_stage(DocStatus.processing, [S.queued, S.queued], False) == ("upload", 5)
    assert nbs.source_stage(DocStatus.processing, [S.routed, S.ready], False)[0] == "route"
    assert nbs.source_stage(DocStatus.processing, [S.cu, S.ready], False)[0] == "cu"
    assert nbs.source_stage(DocStatus.processing, [S.ready, S.ready], False) == ("stitch", 50)
    assert nbs.source_stage(DocStatus.ocr_review, [S.review], False) == ("review", 60)
    assert nbs.source_stage(DocStatus.indexed, [S.approved], False) == ("done", 100)
    assert nbs.source_stage(DocStatus.indexing, [S.approved], True)[0] == "failed"

    notes = [{"id": "1", "title": "受付", "text": "土曜日は午前のみ診療"}, {"id": "2", "title": "x", "text": "abc"}]
    assert [n["id"] for n in nbs.rank_notes(notes, "土曜日の診療時間は？")] == ["1"]
    assert "Answer language: English" in nbs.agent_prompt("en", 3)
    assert "same language as the user's question" in nbs.agent_prompt("auto", 3)


# ================================================================== chat Agentic RAG
def _user_texts(messages):
    return [m.text for m in messages if m.role == "user"]


def _results_seen(messages) -> bool:
    return any(t.startswith(nbs.RESULTS_HEAD) for t in _user_texts(messages))


def test_agent_searches_then_answers_with_pdf_pages_and_weak_flag(container, sample_pdf, monkeypatch):
    c = container
    _search_ready(c)
    nb, src = _nb_with_doc(c, sample_pdf)
    drain(c)
    seen = {}

    def responder(messages, tier, json_mode):
        assert json_mode and nbs.AGENT_MARK in messages[0].text
        if not _results_seen(messages):
            return json.dumps({"action": "search", "query": "M016 Metal crown"})
        seen["results"] = messages[-1].text
        return json.dumps({"action": "answer", "answer": "800 points [1]", "cited": [1], "handoff": False})

    llm = ScriptedLLM(responder)
    c.config.overrides["llm"] = llm
    chunk = next(x for x in c.repo.list_chunks(src["doc_id"]) if x.item_code == "M016")
    monkeypatch.setattr(inspect_svc, "open_weak_pages", lambda c_, d: {chunk.page_from})
    r = nbs.chat(c, nb["id"], "How many points for M016 metal crown?", [], "auto", "en")
    assert set(r) == {"answer", "citations", "handoff", "reason", "steps", "ms", "usage"}
    assert r["answer"] == "800 points [1]" and not r["handoff"] and r["reason"] == ""
    assert [s["type"] for s in r["steps"]] == ["search", "answer"] and r["steps"][0]["hits"] >= 1
    cit = r["citations"][0]
    assert cit["n"] == 1 and cit["kind"] == "chunk" and cit["doc_id"] == src["doc_id"] and cit["doc_name"] == "Sample"
    assert 1 <= cit["page_from"] <= cit["page_to"] <= 3 and cit["excerpt"]
    assert cit["weak"] is (cit["page_from"] <= chunk.page_from <= cit["page_to"])
    assert seen["results"].startswith("Search results for: M016 Metal crown\n[1] ")
    assert r["usage"]["prompt_tokens"] == 2 and len(llm.calls) == 2
    assert r["ms"]["total"] >= 0


def test_agent_step_cap_and_handoff(container, sample_pdf):
    c = container
    _search_ready(c)
    nb, _ = _nb_with_doc(c, sample_pdf)
    drain(c)
    last = {}

    def always_search(messages, tier, json_mode):
        last["msg"] = messages[-1].text
        return json.dumps({"action": "search", "query": f"q{len(messages)}"})

    c.config.overrides["llm"] = llm = ScriptedLLM(always_search)
    r = nbs.chat(c, nb["id"], "crown", [], "auto", "auto")
    opts = c.config.pipeline()[1].notebook
    assert [s["type"] for s in r["steps"]].count("search") == opts.agent_steps
    assert len(llm.calls) == opts.agent_steps + 1 and nbs.FORCE_ANSWER in last["msg"]
    assert r["handoff"] and r["reason"] == "not_in_sources"

    llm.calls.clear()
    r = nbs.chat(c, nb["id"], "crown", [], "deep", "auto")
    assert [s["type"] for s in r["steps"]].count("search") == opts.agent_steps_deep
    assert len(llm.calls) == opts.agent_steps_deep + 1

    def refuse(messages, tier, json_mode):
        if not _results_seen(messages):
            return json.dumps({"action": "search", "query": "weather"})
        return json.dumps({"action": "answer", "answer": "", "cited": [], "handoff": True})

    c.config.overrides["llm"] = ScriptedLLM(refuse)
    r = nbs.chat(c, nb["id"], "weather tomorrow?", [{"role": "user", "content": "hi"}], "auto", "ja")
    assert r["handoff"] and r["reason"] == "not_in_sources" and r["citations"] == []

    # Sổ tay trống → chuyển CSKH ngay, không gọi LLM
    empty = nbs.create_notebook(c, "empty", "u1")
    c.config.overrides["llm"] = llm = ScriptedLLM(refuse)
    r = nbs.chat(c, empty["id"], "anything", [], "auto", "auto")
    assert r["handoff"] and r["reason"] == "no_enabled_sources" and not llm.calls and r["steps"] == []


def test_agent_only_sees_enabled_sources_of_this_notebook(container, sample_pdf):
    c = container
    _search_ready(c)
    other_pdf = make_pdf([["Z900 Orthodontic device", "Orthodontic device is 3,000 points per case."]])
    nb1, src1 = _nb_with_doc(c, sample_pdf, "Sample")
    nb2, src2 = _nb_with_doc(c, other_pdf, "Other")
    drain(c)
    results = []

    def responder(messages, tier, json_mode):
        if not _results_seen(messages):
            return json.dumps({"action": "search", "query": "Z900 Orthodontic device points"})
        results.append(messages[-1].text)
        return json.dumps({"action": "answer", "answer": "see [1]", "cited": [1], "handoff": False})

    c.config.overrides["llm"] = ScriptedLLM(responder)
    r = nbs.chat(c, nb1["id"], "Z900 Orthodontic device points?", [], "auto", "en")
    assert all(x["doc_id"] == src1["doc_id"] for x in r["citations"])
    assert "(Other " not in results[-1] and "(Sample " in results[-1]
    r = nbs.chat(c, nb2["id"], "Z900 Orthodontic device points?", [], "auto", "en")
    assert r["citations"][0]["doc_id"] == src2["doc_id"]

    # Tắt nguồn duy nhất → không còn nguồn nào
    nbs.set_source_enabled(c, nb2, nbs.get_membership(c, nb2["id"], src2["doc_id"]), False, "u1")
    r = nbs.chat(c, nb2["id"], "Z900?", [], "auto", "en")
    assert r["reason"] == "no_enabled_sources"


def test_notes_are_sources_without_search_backend(container):
    c = container  # không cấu hình embedding/search: chỉ có ghi chú
    nb = nbs.create_notebook(c, "notes only", "u1")
    note = nbs.create_note(c, nb, "医院の受付時間", "土曜日は午前のみ診療します。", "u1")

    def responder(messages, tier, json_mode):
        if not _results_seen(messages):
            return json.dumps({"action": "search", "query": "土曜日の診療"})
        return json.dumps({"action": "answer", "answer": "午前のみです [1]", "cited": [1], "handoff": False})

    c.config.overrides["llm"] = ScriptedLLM(responder)
    r = nbs.chat(c, nb["id"], "土曜日の診療時間は？", [], "auto", "ja")
    cit = r["citations"][0]
    assert not r["handoff"] and cit["kind"] == "note" and cit["doc_id"] == note["id"] and cit["page_from"] == 0
    assert cit["doc_name"] == "医院の受付時間" and cit["weak"] is False

    def nothing(messages, tier, json_mode):
        return json.dumps({"action": "search", "query": "zzz qqq"})

    c.config.overrides["llm"] = ScriptedLLM(nothing)
    r = nbs.chat(c, nb["id"], "zzz?", [], "auto", "ja")
    assert r["handoff"] and r["reason"] == "no_source"


class _MockLLM:
    """Đưa ChatMessage qua mock dev (dạng OpenAI dict) như adapter thật gửi tới scripts/demo/mock_ai."""

    def chat(self, messages, *, json_mode=False, tier="main", max_tokens=4096):
        out = mock_notebook.answer([{"role": m.role, "content": m.text} for m in messages], json_mode)
        assert out is not None
        return ChatResult(out, {})


def test_dev_mock_speaks_agent_protocol(container, sample_pdf):
    c = container
    _search_ready(c)
    nb, _ = _nb_with_doc(c, sample_pdf)
    drain(c)
    c.config.overrides["llm"] = _MockLLM()
    r = nbs.chat(c, nb["id"], "M016 Metal crown points per tooth", [], "auto", "en")
    assert not r["handoff"] and "[1]" in r["answer"] and r["answer"].startswith("According to")
    assert r["citations"] and r["steps"][0] == {
        "type": "search",
        "query": "M016 Metal crown points per tooth",
        "hits": 3,
    }
    r = nbs.chat(c, nb["id"], "ねこ", [], "auto", "auto")
    assert r["handoff"] and [s["type"] for s in r["steps"]].count("search") >= 1
    assert mock_notebook.answer([{"role": "system", "content": "other"}], True) is None


def test_edit_while_indexing_is_deferred_then_reindexed(container):
    """Sửa phần tử khi tài liệu sổ tay đang chunk/index: không chặn, ghi cờ, index xong thì chạy lại."""
    from app.domain.models import Document
    from app.services import notebooks as nbs

    c = container
    doc = Document(id="d1", name="x", auto_review=True, status=DocStatus.indexing)
    c.repo.save_doc(doc)
    nbs.reindex_document(c, "d1", "u1")
    assert c.repo.s.get(nbs.FLAGS, "d1", "reindex_pending")["by"] == "u1"
    called = []
    orig = nbs.reindex_document
    nbs.reindex_document = lambda c_, d, a: called.append((d, a))
    try:
        nbs.run_pending_reindex(c, "d1")
        nbs.run_pending_reindex(c, "d1")  # cờ đã xoá → không chạy lại lần 2
    finally:
        nbs.reindex_document = orig
    assert called == [("d1", "u1")]
