"""UI v2 — service Sổ tay (backend A1): notebook, ghi chú, upload tự chạy pipeline, chat Agentic RAG.

Lưu trong DocStore chung (`c.repo.s`):
  notebooks          pk "_"          {id, name, created_by, created_at, updated_at}
  notebook_sources   pk <notebook>   id = doc_id, {doc_id, enabled, added_at}   (mỗi nguồn một bản ghi → upload
                                     song song không ghi đè lẫn nhau)
  notes              pk <notebook>   {id, title, text, created_by, created_at, updated_at}

Chat: agent gọi LLM nhiều lượt (json_mode). Mỗi lượt LLM trả `{"action":"search","query":...}` hoặc
`{"action":"answer","answer":...,"cited":[n],"handoff":bool}`. Nguồn = chunk của các tài liệu đang bật + ghi chú,
đánh số [1..n] ổn định qua các lượt. Không log câu hỏi / nội dung — chỉ mã + id + số đếm.
"""

from __future__ import annotations

import io
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from app.core.text import keyword_score, keyword_terms, nfkc
from app.core.util import new_id, now_iso
from app.domain.models import GLOBAL, DocStatus, Document, JobStatus, PageStatus
from app.ports import ChatMessage
from app.services import pipeline as pl
from app.services.container import Container
from app.services.jobs import emit

log = logging.getLogger("hoken.notebooks")

NB, SRC, NOTES = "notebooks", "notebook_sources", "notes"
FLAGS = "doc_flags"  # cờ theo tài liệu, vd reindex_pending
AUTO_ACTOR = pl.AUTO
SOURCE_CHARS = 1800  # cắt mỗi đoạn gửi cho LLM
EXCERPT_CHARS = 300
PIPELINE_STEPS = {"docling", "route", "cu", "stitch", "auto_review", "chunk", "index"}


# ================================================================== notebook
def get_notebook(c: Container, nb_id: str) -> dict | None:
    return c.repo.s.get(NB, GLOBAL, nb_id)


def _touch(c: Container, nb: dict) -> dict:
    nb["updated_at"] = now_iso()
    c.repo.s.put(NB, GLOBAL, nb["id"], nb)
    return nb


def memberships(c: Container, nb_id: str) -> list[dict]:
    return c.repo.s.query(SRC, nb_id, limit=1000)


def get_membership(c: Container, nb_id: str, doc_id: str) -> dict | None:
    return c.repo.s.get(SRC, nb_id, doc_id)


def list_notes(c: Container, nb_id: str) -> list[dict]:
    return c.repo.s.query(NOTES, nb_id, limit=1000)


def summary(c: Container, nb: dict) -> dict:
    return {
        "id": nb["id"],
        "name": nb["name"],
        "source_count": len(memberships(c, nb["id"])),
        "note_count": len(list_notes(c, nb["id"])),
        "created_by": nb.get("created_by", ""),
        "created_at": nb.get("created_at", ""),
        "updated_at": nb.get("updated_at", ""),
    }


def detail(c: Container, nb: dict) -> dict:
    sources = []
    for m in memberships(c, nb["id"]):
        doc = c.repo.get_doc(m["doc_id"])
        if doc:
            sources.append(source_view(c, doc, m))
    return {**summary(c, nb), "sources": sources, "notes": [note_view(n) for n in list_notes(c, nb["id"])]}


def list_notebooks(c: Container) -> list[dict]:
    return [summary(c, nb) for nb in c.repo.s.query(NB, GLOBAL, desc=True, limit=1000)]


def create_notebook(c: Container, name: str, actor: str) -> dict:
    now = now_iso()
    nb = {"id": new_id(), "name": name.strip(), "created_by": actor, "created_at": now, "updated_at": now}
    c.repo.s.put(NB, GLOBAL, nb["id"], nb)
    c.repo.audit(actor, "notebook.create", nb["id"])
    return nb


def rename_notebook(c: Container, nb: dict, name: str, actor: str) -> dict:
    nb["name"] = name.strip()
    c.repo.audit(actor, "notebook.rename", nb["id"])
    return _touch(c, nb)


def delete_notebook(c: Container, nb: dict, actor: str) -> None:
    """Xoá sổ tay cùng mọi tài liệu nguồn và ghi chú. Nguồn đang chạy job → `doc_busy`, không xoá gì."""
    docs = [m["doc_id"] for m in memberships(c, nb["id"])]
    for d in docs:
        if any(j.status in (JobStatus.queued, JobStatus.running) for j in c.repo.list_jobs({"doc_id": d})):
            raise pl.PipelineError("doc_busy")
    for d in docs:
        if c.repo.get_doc(d):
            pl.delete_document(c, d, actor)
    c.repo.s.delete_partition(SRC, nb["id"])
    c.repo.s.delete_partition(NOTES, nb["id"])
    c.repo.s.delete(NB, GLOBAL, nb["id"])
    c.repo.audit(actor, "notebook.delete", nb["id"], sources=len(docs))


# ================================================================== nguồn
def to_pdf(data: bytes) -> tuple[bytes, str]:
    """PDF giữ nguyên; PNG/JPEG → PDF 1 trang (cạnh dài ≈ A4 khi render 72 dpi, ảnh gốc giữ nguyên độ phân giải)."""
    if data.startswith(b"%PDF"):
        return data, "pdf"
    if not (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")):
        raise pl.PipelineError("unsupported_file")
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise pl.PipelineError("bad_image") from e
    resolution = max(72.0, max(img.size) * 72.0 / 842.0)
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=resolution)
    return buf.getvalue(), "image"


def add_source(c: Container, nb: dict, *, data: bytes, filename: str, name: str, actor: str) -> dict:
    pdf, file_type = to_pdf(data)
    opts = c.config.pipeline()[1].notebook
    doc = pl.create_document(
        c,
        data=pdf,
        filename=filename,
        name=name.strip() or filename,
        kind="other",
        book_page_start=1,
        page_from=None,
        page_to=None,
        actor=actor,
        auto_review=opts.auto_review,
        file_type=file_type,
    )
    if file_type == "image":  # kích thước của file khách tải lên, không phải PDF đã đổi
        doc.size_bytes = len(data)
        doc = c.repo.save_doc(doc)
    m = {"doc_id": doc.id, "enabled": True, "added_at": now_iso()}
    c.repo.s.put(SRC, nb["id"], doc.id, m)
    _touch(c, nb)
    c.repo.audit(actor, "notebook.source_add", nb["id"], doc=doc.id, file_type=file_type)
    return source_view(c, doc, m)


def set_source_enabled(c: Container, nb: dict, m: dict, enabled: bool, actor: str) -> dict:
    m["enabled"] = bool(enabled)
    c.repo.s.put(SRC, nb["id"], m["doc_id"], m)
    _touch(c, nb)
    c.repo.audit(actor, "notebook.source_enabled", nb["id"], doc=m["doc_id"], enabled=m["enabled"])
    return source_view(c, c.repo.get_doc(m["doc_id"]), m)


def remove_source(c: Container, nb: dict, doc_id: str, actor: str) -> None:
    if c.repo.get_doc(doc_id):
        pl.delete_document(c, doc_id, actor)  # doc_busy nếu đang chạy job
    c.repo.s.delete(SRC, nb["id"], doc_id)
    _touch(c, nb)


_PRE = {
    PageStatus.queued: 0.0,
    PageStatus.docling: 0.2,
    PageStatus.routed: 0.4,
    PageStatus.cu: 0.6,
}


def source_stage(status: DocStatus, page_statuses: list[PageStatus], failed: bool) -> tuple[str, int]:
    """(stage, progress 0..100) của một nguồn — suy ra từ trạng thái tài liệu + trang. Hàm thuần."""
    by_doc = {
        DocStatus.stitching: ("stitch", 55),
        DocStatus.ocr_review: ("review", 60),
        DocStatus.ready_for_chunking: ("chunk", 65),
        DocStatus.chunking: ("chunk", 70),
        DocStatus.chunk_review: ("index", 85),
        DocStatus.indexing: ("index", 90),
        DocStatus.indexed: ("done", 100),
    }
    if status in by_doc:
        stage, progress = by_doc[status]
    else:
        n = len(page_statuses) or 1
        progress = 5 + int(45 * sum(_PRE.get(s, 1.0) for s in page_statuses) / n)
        if page_statuses and all(s == PageStatus.queued for s in page_statuses):
            stage = "upload"
        elif any(s in (PageStatus.queued, PageStatus.docling) for s in page_statuses):
            stage = "docling"
        elif any(s == PageStatus.routed for s in page_statuses):
            stage = "route"
        elif any(s == PageStatus.cu for s in page_statuses):
            stage = "cu"
        else:
            stage = "stitch"
    if failed or status == DocStatus.failed:
        return "failed", progress
    return stage, progress


def _quality(c: Container, doc_id: str) -> tuple[dict | None, int]:
    """Điểm + hạng + số điểm yếu chưa xử lý từ service Kiểm tra (A2). Chưa có → (None, 0)."""
    from app.services import inspect

    fn = getattr(inspect, "doc_quality", None)
    if fn is None:
        return None, 0
    try:
        q = fn(c, doc_id)
    except Exception:  # noqa: BLE001 — thẻ nguồn vẫn hiện khi chưa chấm được
        return None, 0
    if q is None:
        return None, 0
    if hasattr(q, "model_dump"):
        q = q.model_dump(mode="json")
    return {"score": q["score"], "grade": q["grade"]}, int(q.get("weak_open", 0))


def source_view(c: Container, doc: Document, m: dict) -> dict:
    pages = c.repo.list_pages(doc.id)
    failed = next(
        (j for j in c.repo.list_jobs({"doc_id": doc.id}) if j.status == JobStatus.failed and j.step in PIPELINE_STEPS),
        None,
    )
    stage, progress = source_stage(doc.status, [p.status for p in pages], failed is not None)
    quality, weak_open = _quality(c, doc.id) if stage == "done" else (None, 0)
    error = ""
    if stage == "failed":
        error = (failed.error if failed else "") or next((p.error for p in pages if p.error), "")
    return {
        "doc_id": doc.id,
        "name": doc.name,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "status": doc.status.value,
        "stage": stage,
        "progress": progress,
        "pages": doc.n_pages,
        "quality": quality,
        "weak_open": weak_open,
        "enabled": bool(m.get("enabled", True)),
        "error": error[:300],
        "created_at": doc.created_at,
    }


def reindex_document(c, doc_id: str, actor: str) -> None:
    """Gọi sau khi nội dung trang của tài liệu auto_review bị sửa (backend A2 gọi): chunk + index lại.
    Tài liệu không phải auto_review thì không làm gì."""
    doc = c.repo.get_doc(doc_id)
    if not doc or not doc.auto_review:
        return None
    if doc.status in (DocStatus.chunking, DocStatus.indexing):
        # Đang chunk/index: không chặn người sửa — ghi cờ, job index xong sẽ chạy lại (run_pending_reindex)
        c.repo.s.put(FLAGS, doc_id, "reindex_pending", {"id": "reindex_pending", "by": actor, "at": now_iso()})
        return None
    pages = c.repo.list_pages(doc_id)
    if not pages or any(p.status not in (PageStatus.review, PageStatus.approved) for p in pages):
        return None  # còn trang chưa qua nối trang / lỗi — luồng tự động sẽ chạy tiếp hoặc cần Retry
    pl.auto_approve_pages(c, doc_id)
    emit(c, doc_id, "auto.reindex", by=actor)
    pl.start_chunking(c, doc_id, actor)
    return None


def run_pending_reindex(c, doc_id: str) -> None:
    """Gọi khi job index của tài liệu auto_review xong: có sửa trong lúc chạy thì chunk + index lại."""
    flag = c.repo.s.get(FLAGS, doc_id, "reindex_pending")
    if not flag:
        return None
    c.repo.s.delete(FLAGS, doc_id, "reindex_pending")
    reindex_document(c, doc_id, flag.get("by") or AUTO_ACTOR)
    return None


# ================================================================== ghi chú
def note_view(n: dict) -> dict:
    return {k: n.get(k, "") for k in ("id", "title", "text", "created_by", "created_at", "updated_at")}


def create_note(c: Container, nb: dict, title: str, text: str, actor: str) -> dict:
    now = now_iso()
    n = {"id": new_id(), "title": title.strip(), "text": text, "created_by": actor, "created_at": now}
    n["updated_at"] = now
    c.repo.s.put(NOTES, nb["id"], n["id"], n)
    _touch(c, nb)
    return note_view(n)


def update_note(c: Container, nb: dict, n: dict, title: str | None, text: str | None) -> dict:
    if title is not None:
        n["title"] = title.strip()
    if text is not None:
        n["text"] = text
    n["updated_at"] = now_iso()
    c.repo.s.put(NOTES, nb["id"], n["id"], n)
    _touch(c, nb)
    return note_view(n)


def delete_note(c: Container, nb: dict, note_id: str) -> None:
    c.repo.s.delete(NOTES, nb["id"], note_id)
    _touch(c, nb)


# ================================================================== chat Agentic RAG
AGENT_MARK = "notebook research agent"
LANG_NAMES = {"ja": "Japanese (日本語)", "en": "English", "vi": "Vietnamese (Tiếng Việt)"}
FORCE_ANSWER = 'Search limit reached. Reply now with {"action":"answer",...} using only the sources above.'
RESULTS_HEAD = "Search results for: "


def agent_prompt(lang: str, max_searches: int) -> str:
    language = LANG_NAMES.get(lang, "the same language as the user's question")
    return (
        f"You are a {AGENT_MARK} for Japanese dental insurance (保険点数) documents. You can only use the "
        "notebook's sources (document chunks and user notes) that your searches return.\n"
        "Reply with ONE JSON object per turn, nothing else:\n"
        '- {"action":"search","query":"<short search query>"} to search the sources '
        f"(at most {max_searches} searches; rephrase or narrow the query if results are not relevant);\n"
        '- {"action":"answer","answer":"<answer>","cited":[<source numbers>],"handoff":false} when you can '
        "answer. Cite every fact with its source number like [1] inside the answer text.\n"
        "Always search before answering. If the sources do not contain the answer, reply "
        '{"action":"answer","answer":"","cited":[],"handoff":true} — never guess or use outside knowledge.\n'
        f"Answer language: {language}."
    )


@dataclass
class Source:
    key: str
    kind: str  # chunk | note
    doc_id: str  # id tài liệu; với ghi chú là id ghi chú (hợp đồng với frontend)
    label: str  # tên tài liệu / tiêu đề ghi chú
    item_code: str
    title: str
    page_from: int  # trang PDF (đã đổi từ trang sách); 0 với ghi chú
    page_to: int
    content: str


def book_to_pdf(doc: Document, book_page: int) -> int:
    """Trang trong sách (chunk) → trang PDF (viewer), kẹp trong dải trang đã xử lý."""
    pdf = doc.page_from + book_page - doc.book_page_start
    return max(doc.page_from, min(doc.page_to, pdf))


def format_results(query: str, numbered: list[tuple[int, Source]]) -> str:
    if not numbered:
        return f"{RESULTS_HEAD}{query}\n(no results)"
    blocks = []
    for n, s in numbered:
        if s.kind == "note":
            head = f"[{n}] (note) {s.label}"
        else:
            pages = f"p.{s.page_from}" + ("" if s.page_to == s.page_from else f"-{s.page_to}")
            head = f"[{n}] {s.item_code or '-'} {s.title} ({s.label} {pages})"
        blocks.append(f"{head}\n{s.content[:SOURCE_CHARS]}")
    return f"{RESULTS_HEAD}{query}\n" + "\n\n".join(blocks)


def parse_action(text: str) -> dict[str, Any]:
    """Đọc lượt của agent. Sai dạng JSON → coi cả chữ là câu trả lời (trích [n] trong chữ)."""
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise TypeError
    except (ValueError, TypeError):
        return {"action": "answer", "answer": text.strip(), "cited": _cites(text), "handoff": False}
    if data.get("action") == "search" and str(data.get("query") or "").strip():
        return {"action": "search", "query": str(data["query"]).strip()[:300]}
    answer = str(data.get("answer") or "").strip()
    cited = []
    for x in data.get("cited") or []:
        try:
            cited.append(int(x))
        except (TypeError, ValueError):
            continue
    return {
        "action": "answer",
        "answer": answer,
        "cited": sorted(set(cited + _cites(answer))),
        "handoff": bool(data.get("handoff")) or not answer,
    }


def _cites(text: str) -> list[int]:
    return [int(m) for m in re.findall(r"\[(\d+)\]", text)]


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", "", nfkc(text).lower())
    return {t[i : i + 2] for i in range(len(t) - 1)}


def rank_notes(notes: list[dict], query: str, limit: int = 3) -> list[dict]:
    """Ghi chú khớp câu tìm: từ khoá (kanji/katakana/chữ-số) + tỉ lệ cặp ký tự chung. Đơn giản, đủ cho demo."""
    terms, qb = keyword_terms(query), _bigrams(query)
    scored = []
    for n in notes:
        body = f"{n.get('title', '')}\n{n.get('text', '')}"
        ratio = len(qb & _bigrams(body)) / len(qb) if qb else 0.0
        score = keyword_score(body, terms) + 10 * ratio
        if ratio >= 0.2 or keyword_score(body, terms) > 0:
            scored.append((score, n))
    scored.sort(key=lambda x: -x[0])
    return [n for _, n in scored[:limit]]


class _Agent:
    def __init__(self, c: Container, nb_id: str, top_k: int):
        self.c, self.top_k = c, top_k
        self.docs = {}
        for m in memberships(c, nb_id):
            if m.get("enabled", True):
                d = c.repo.get_doc(m["doc_id"])
                if d:
                    self.docs[d.id] = d
        self.notes = list_notes(c, nb_id)
        self.sources: list[Source] = []
        self.numbers: dict[str, int] = {}

    def _number(self, s: Source) -> int:
        if s.key not in self.numbers:
            self.sources.append(s)
            self.numbers[s.key] = len(self.sources)
        return self.numbers[s.key]

    def search(self, query: str) -> list[tuple[int, Source]]:
        found: list[Source] = []
        cfg = self.c.config
        ready = cfg.is_configured("embedding") and cfg.is_configured("search")
        # Chưa có tài liệu nào index xong và chưa cấu hình tìm kiếm → chỉ tìm trong ghi chú (không báo lỗi)
        if self.docs and (ready or any(d.status == DocStatus.indexed for d in self.docs.values())):
            emb, idx = self.c.config.adapter("embedding"), self.c.config.adapter("search")
            # Index không có bộ lọc theo sổ tay → lấy dư rồi chỉ giữ tài liệu đang bật của sổ tay này
            k = min(50, self.top_k * 5)
            hits = [h for h in idx.search(query, emb.embed([query])[0], k) if h.doc_id in self.docs]
            for h in hits[: self.top_k]:
                d = self.docs[h.doc_id]
                found.append(
                    Source(
                        key=h.id,
                        kind="chunk",
                        doc_id=d.id,
                        label=d.name,
                        item_code=h.item_code,
                        title=h.title,
                        page_from=book_to_pdf(d, h.page_from),
                        page_to=book_to_pdf(d, max(h.page_from, h.page_to)),
                        content=h.content,
                    )
                )
        for n in rank_notes(self.notes, query, limit=max(1, self.top_k // 2)):
            found.append(
                Source(f"note:{n['id']}", "note", n["id"], n.get("title", ""), "", "", 0, 0, n.get("text", ""))
            )
        return [(self._number(s), s) for s in found]

    def citations(self, cited: list[int]) -> list[dict]:
        from app.services import inspect

        weak: dict[str, set[int]] = {}
        out = []
        for n in cited:
            s = self.sources[n - 1]
            is_weak = False
            if s.kind == "chunk":
                if s.doc_id not in weak:
                    try:
                        weak[s.doc_id] = set(inspect.open_weak_pages(self.c, s.doc_id))
                    except Exception:  # noqa: BLE001 — chưa có dữ liệu kiểm tra thì không gắn ⚠
                        weak[s.doc_id] = set()
                is_weak = any(p in weak[s.doc_id] for p in range(s.page_from, s.page_to + 1))
            out.append(
                {
                    "n": n,
                    "kind": s.kind,
                    "doc_id": s.doc_id,
                    "doc_name": s.label,
                    "page_from": s.page_from,
                    "page_to": s.page_to,
                    "item_code": s.item_code,
                    "excerpt": s.content[:EXCERPT_CHARS],
                    "weak": is_weak,
                }
            )
        return out


def _add_usage(total: dict[str, int], usage: dict[str, int]) -> None:
    for k, v in (usage or {}).items():
        if isinstance(v, int | float):
            total[k] = total.get(k, 0) + int(v)


def chat(
    c: Container, nb_id: str, question: str, history: list[dict[str, str]], mode: str = "auto", lang: str = "auto"
) -> dict[str, Any]:
    """Trả lời câu hỏi bằng agent tìm-rồi-trả-lời trên nguồn đang bật + ghi chú. Ném NotConfigured nếu thiếu
    LLM (hoặc embedding/search khi có tài liệu đã index)."""
    t0 = time.monotonic()
    opts = c.config.pipeline()[1]
    nopts = opts.notebook
    max_searches = max(1, nopts.agent_steps_deep if mode == "deep" else nopts.agent_steps)
    agent = _Agent(c, nb_id, max(1, nopts.top_k))
    out: dict[str, Any] = {"answer": "", "citations": [], "handoff": True, "steps": [], "usage": {}}

    def done(reason: str) -> dict[str, Any]:
        out["reason"] = reason
        out["ms"] = {"total": int((time.monotonic() - t0) * 1000)}
        log.info(
            "notebook.chat nb=%s mode=%s steps=%d sources=%d handoff=%s reason=%s",
            nb_id,
            mode,
            len(out["steps"]),
            len(agent.sources),
            out["handoff"],
            reason or "-",
        )
        return out

    if not agent.docs and not agent.notes:
        return done("no_enabled_sources")

    llm = c.config.adapter("llm")
    msgs = [ChatMessage("system", agent_prompt(lang, max_searches))]
    hist = history[-opts.chat.max_history * 2 :] if opts.chat.max_history > 0 else []
    for turn in hist:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            msgs.append(ChatMessage(turn["role"], str(turn["content"])[:4000]))
    msgs.append(ChatMessage("user", f"Question: {question}"))

    searches = 0
    act: dict[str, Any] = {"action": "answer", "answer": "", "cited": [], "handoff": True}
    for _ in range(max_searches + 1):
        res = llm.chat(msgs, json_mode=True, max_tokens=1500)
        _add_usage(out["usage"], res.usage)
        act = parse_action(res.text)
        if act["action"] != "search":
            break
        if searches >= max_searches:  # đã hết lượt tìm mà vẫn đòi tìm → coi như không trả lời được
            act = {"action": "answer", "answer": "", "cited": [], "handoff": True}
            break
        searches += 1
        numbered = agent.search(act["query"])
        out["steps"].append({"type": "search", "query": act["query"], "hits": len(numbered)})
        msgs.append(ChatMessage("assistant", json.dumps({"action": "search", "query": act["query"]})))
        results = format_results(act["query"], numbered)
        if searches >= max_searches:
            results += "\n\n" + FORCE_ANSWER
        msgs.append(ChatMessage("user", results))
    out["steps"].append({"type": "answer"})

    if not agent.sources:
        return done("no_source")
    cited = [n for n in act["cited"] if 1 <= n <= len(agent.sources)]
    if act["handoff"] or not act["answer"]:
        out["answer"] = act["answer"]
        return done("not_in_sources")
    out.update(answer=act["answer"], citations=agent.citations(cited), handoff=False)
    return done("")
