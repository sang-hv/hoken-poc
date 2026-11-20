"""UI v2 — service Kiểm tra (backend A2): phần tử theo thứ tự đọc, điểm yếu, chất lượng, sửa / đọc lại.

Lưu trữ (blob, theo khoá docId + trang):
  - `pages/NNNN/elements.json`  {basis, md_version, image_size, vlm?, elements[]} — dựng lười khi GET nếu chưa có
    hoặc đã cũ (engine/CU đổi → dựng lại; phiên bản Markdown đổi từ nơi khác → gán lại, giữ trạng thái đã xử lý).
  - `pages/NNNN/inspect_log.json` lịch sử sửa phần tử (chỉ id, nguồn, điểm — không chép nội dung)
  - `docs/{doc}/insights.json`   tóm tắt + ý chính do LLM tạo

Log / audit chỉ ghi id, trang, mã phần tử, số phiên bản (CLAUDE.md) — không chép nội dung tài liệu.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

from app.core.util import now_iso
from app.domain.models import DocStatus, Document, Page, PageStatus
from app.ports import ChatMessage
from app.services import pipeline as pl
from app.services.config_service import NotConfigured
from app.services.container import Container
from app.services.jobs import emit
from app.steps import elements as E
from app.steps import rules
from app.steps.common import crop_png, k_page, k_source, render_page_png

log = logging.getLogger("hoken.inspect")

ELEMENTS = "elements.json"
LOG = "inspect_log.json"
STATE_VERSION = 1
AUTO = "auto"
AUTO_REREAD_MAX_PER_PAGE = 10
SCORE_MAX_PAGES = 5
READY = (PageStatus.review, PageStatus.approved)
PUBLIC = (
    "id",
    "order",
    "label",
    "bbox",
    "text",
    "confidence",
    "source",
    "weak",
    "status",
    "edited_by",
    "edited_at",
)

# Dấu nhận biết trong prompt (mock dev `scripts/demo/mock_inspect.py` dựa vào đây)
REREAD_MARK = "[hoken:element-reread]"
SCORE_MARK = "[hoken:page-score]"
INSIGHTS_MARK = "[hoken:insights]"

REREAD_MAX = 4000  # độ dài tối đa của hướng dẫn đọc lại người dùng nhập


def reread_system(guide: str) -> str:
    """System prompt đọc lại: dấu + vai trò + hướng dẫn (settings `quality.reread_prompt` hoặc người dùng sửa)
    + khung JSON cố định (để luôn parse được)."""
    return (
        f"{REREAD_MARK} You transcribe ONE cropped region of a page of a Japanese dental insurance document "
        "(public MHLW material) into Markdown.\n\n"
        f"{guide.strip()}\n\n"
        'Return JSON {"markdown": string, "confidence": number between 0 and 1 (how sure you are of the reading)}.'
    )


SCORE_PROMPT = (
    f"{SCORE_MARK} You grade OCR quality. You get one page image of a Japanese dental insurance document and the "
    "Markdown extracted from it. Compare them: missing or wrong text, wrong numbers/点, broken tables, missing "
    'figure descriptions. Return JSON {"score": integer 0-100 (100 = perfect), "comment": short comment in '
    "Japanese}."
)
INSIGHTS_PROMPT = (
    f"{INSIGHTS_MARK} You summarise a Japanese dental insurance document (public MHLW material) for clinic staff. "
    'Answer in Japanese. Return JSON {"summary": string (3-5 sentences), "key_points": [up to 6 short strings, '
    "keep item codes and 点 numbers exactly]}."
)


class InspectError(pl.PipelineError):
    pass


# ================================================================== tiện ích
def _opts(c: Container):
    return c.config.pipeline()[1]


def _doc(c: Container, doc_id: str) -> Document:
    d = c.repo.get_doc(doc_id)
    if not d:
        raise InspectError("doc_not_found")
    return d


def _page(c: Container, doc_id: str, n: int) -> Page:
    p = c.repo.get_page(doc_id, n)
    if not p:
        raise InspectError("page_not_found")
    return p


def _json(c: Container, key: str) -> Any:
    if not c.blob.exists(key):
        return None
    try:
        return json.loads(c.blob.get(key))
    except ValueError:
        return None


def _put_json(c: Container, key: str, data: Any) -> None:
    c.blob.put(key, json.dumps(data, ensure_ascii=False).encode(), "application/json")


def _basis(p: Page) -> str:
    return f"v{STATE_VERSION}|{p.engine}|{p.cu_status}|{p.route or ''}"


def _page_png(c: Container, doc_id: str, n: int) -> bytes:
    key = k_page(doc_id, n, "image.png")
    if c.blob.exists(key):
        return c.blob.get(key)
    png, _ = render_page_png(c.blob.get(k_source(doc_id)), n)
    c.blob.put(key, png, "image/png")
    return png


def _neighbours(c: Container, doc_id: str, n: int) -> tuple[bool, bool]:
    prev = c.repo.get_page(doc_id, n - 1) if n > 1 else None
    cur = c.repo.get_page(doc_id, n)
    return bool(prev and prev.table_continues_next), bool(cur and cur.table_continues_next)


def _scanned(p: Page) -> bool:
    return (not p.features.has_text_layer) or p.scores.ocr_score is not None


# ================================================================== dựng & đánh giá phần tử
def _build(c: Container, doc: Document, p: Page, markdown: str) -> tuple[list[dict], list | None]:
    meta = _json(c, k_page(doc.id, p.page, "docling.json")) or {}
    cu_raw = _json(c, k_page(doc.id, p.page, "cu.json")) if p.cu_status == "done" else None
    tokens: list[E.Tok] = []
    need_tokens = not (cu_raw and ((cu_raw.get("result") or {}).get("contents"))) and (
        meta.get("engine") != "docling" or any(e.get("text") is None for e in meta.get("elements") or [])
    )
    if need_tokens and c.blob.exists(k_source(doc.id)):
        tokens = E.pdfium_tokens(c.blob.get(k_source(doc.id)), p.page)
    els = E.build_page_elements(
        markdown=markdown,
        cu_raw=cu_raw,
        docling_meta=meta,
        tokens=tokens,
        complex_tables=p.features.complex_tables,
    )
    for e in els:
        e.update(status="", edited_by="", edited_at="")
    return els, meta.get("image_size")


def assess(c: Container, doc: Document, p: Page, state: dict, markdown: str | None = None) -> dict:
    """Tính lại điểm yếu + trạng thái từng phần tử và điểm trang (gọi sau mọi thay đổi)."""
    q = _opts(c).quality
    prev, nxt = _neighbours(c, doc.id, p.page)
    els = state["elements"]
    for e in els:
        e["weak"] = rules.element_weak_flags(e, q, table_continues_prev=prev, table_continues_next=nxt)
    md = markdown if markdown is not None else E.rebuild_markdown(els)
    flag = rules.page_level_flag(els, md, q, scanned=_scanned(p), ocr_score=p.scores.ocr_score)
    if flag:
        if not els:
            els.append(
                {
                    "id": "e1",
                    "order": 1,
                    "label": "text",
                    "bbox": [0.0, 0.0, 1.0, 1.0],
                    "text": "",
                    "raw_text": "",
                    "confidence": None,
                    "source": "pdfium",
                    "sep": "\n\n",
                    "raw": {"engine": "page"},
                    "status": "",
                    "edited_by": "",
                    "edited_at": "",
                    "weak": [],
                }
            )
        target = next((e for e in els if E.is_content(e)), els[0])
        target["weak"].append(flag)
    for e in els:
        e["status"] = rules.element_status(e["weak"], e.get("status", ""))
    vlm = state.get("vlm")
    vlm_score = vlm["score"] if vlm and vlm.get("md_version") == state.get("md_version") else None
    state["score"] = rules.page_quality_score(els, vlm_score)
    state["grade"] = rules.quality_grade(state["score"], q)
    return state


def _carry_over(old: list[dict], new: list[dict]) -> None:
    """Gán lại sau khi Markdown đổi từ nơi khác: phần tử cùng id, nhãn và nội dung giữ trạng thái đã xử lý."""
    by_id = {e["id"]: e for e in old}
    for e in new:
        o = by_id.get(e["id"])
        if o and o["label"] == e["label"] and o.get("text", "").strip() == e.get("text", "").strip():
            for k in ("status", "edited_by", "edited_at", "source", "confidence", "reread_from"):
                if k in o:
                    e[k] = o[k]


def load_state(c: Container, doc: Document, p: Page, *, build: bool = True) -> dict | None:
    """Phần tử của trang (dựng lười). Trang chưa qua nối trang → lỗi page_not_ready (build) / None."""
    key = k_page(doc.id, p.page, ELEMENTS)
    state = _json(c, key)
    fresh = state is not None and state.get("basis") == _basis(p) and state.get("md_version") == p.current_version
    if fresh or not build:
        return state
    if p.status not in READY:
        raise InspectError("page_not_ready")
    md = pl.page_markdown(c, p)
    els, image_size = _build(c, doc, p, md)
    if state is not None and state.get("basis") == _basis(p):
        _carry_over(state.get("elements") or [], els)
    new = {
        "basis": _basis(p),
        "md_version": p.current_version,
        "image_size": image_size or (state or {}).get("image_size"),
        "vlm": (state or {}).get("vlm"),
        "elements": els,
    }
    assess(c, doc, p, new, md)
    _put_json(c, key, new)
    return new


def _save_state(c: Container, doc_id: str, n: int, state: dict) -> None:
    _put_json(c, k_page(doc_id, n, ELEMENTS), state)


def public(e: dict) -> dict:
    return {k: e.get(k) for k in PUBLIC} | {"weak": list(e.get("weak") or []), "edited_by": e.get("edited_by") or ""}


def page_view(doc: Document, p: Page, state: dict) -> dict:
    size = state.get("image_size")
    return {
        "page": p.page,
        "book_page": p.book_page,
        "image_size": list(size) if size else None,
        "score": state["score"],
        "grade": state["grade"],
        "elements": [public(e) for e in sorted(state["elements"], key=lambda e: e["order"])],
    }


def page_elements(c: Container, doc_id: str, n: int) -> dict:
    doc, p = _doc(c, doc_id), _page(c, doc_id, n)
    return page_view(doc, p, load_state(c, doc, p))


def _element(state: dict, eid: str) -> dict:
    e = next((x for x in state["elements"] if x["id"] == eid), None)
    if e is None:
        raise InspectError("element_not_found")
    return e


def element_image(c: Container, doc_id: str, n: int, eid: str) -> bytes:
    doc, p = _doc(c, doc_id), _page(c, doc_id, n)
    e = _element(load_state(c, doc, p), eid)
    return crop_png(_page_png(c, doc_id, n), e["bbox"])


def element_raw(c: Container, doc_id: str, n: int, eid: str) -> dict:
    doc, p = _doc(c, doc_id), _page(c, doc_id, n)
    return _element(load_state(c, doc, p), eid)


# ================================================================== lịch sử
def _log(c: Container, doc_id: str, n: int, entry: dict) -> None:
    key = k_page(doc_id, n, LOG)
    items = _json(c, key) or []
    items.append(entry)
    _put_json(c, key, items[-500:])


def page_history(c: Container, doc_id: str, n: int) -> list[dict]:
    _doc(c, doc_id)
    p = _page(c, doc_id, n)
    out = [
        {
            "at": v.at,
            "by": v.by,
            "kind": "page_version",
            "element_id": "",
            "summary": f"v{v.v} · {v.source}"
            + (f" · {v.note}" if v.note and not v.source.startswith("element") else ""),
        }
        for v in p.versions
        if not v.source.startswith("element_")  # sửa phần tử đã có dòng riêng bên dưới
    ]
    out += _json(c, k_page(doc_id, n, LOG)) or []
    return sorted(out, key=lambda x: x.get("at", ""), reverse=True)


# ================================================================== sửa / đọc lại / xác nhận
def _require_editable(c: Container, doc: Document, p: Page) -> None:
    # Tài liệu tự chạy (auto_review): cho sửa cả khi đang chunk/index — reindex_document ghi cờ và chạy lại sau
    if not doc.auto_review and doc.status in (DocStatus.chunking, DocStatus.indexing):
        raise InspectError("doc_busy")
    if p.status not in READY:
        raise InspectError("page_not_ready")


def _fmt(conf) -> str:
    return "-" if conf is None else f"{float(conf):.2f}"


def _commit(c: Container, doc: Document, p: Page, state: dict, source: str, actor: str, note: str) -> int:
    """Ghép lại Markdown của trang từ phần tử → phiên bản mới (nếu khác) → đánh giá lại → lưu. Trả số phiên bản."""
    md = E.rebuild_markdown(state["elements"])
    if md.strip() != pl.page_markdown(c, p).strip():
        p = pl.save_version(c, p, md, source, actor, note=note)
    state["md_version"] = p.current_version
    assess(c, doc, p, state, md)
    _save_state(c, doc.id, p.page, state)
    return p.current_version


FLAGS = "doc_flags"  # cờ theo tài liệu (DocStore), vd reindex_pending


def reindex_document(c: Container, doc_id: str, actor: str, pages: list[int] | None = None) -> None:
    """Sau khi nội dung trang của tài liệu auto_review bị sửa: chunk + index lại. Tài liệu duyệt tay: không làm gì.
    `pages` (trang PDF vừa sửa): chỉ chunk lại các mục dính tới các trang đó, giữ chunk khác (kể cả sửa tay);
    None = chunk lại toàn bộ."""
    doc = c.repo.get_doc(doc_id)
    if not doc or not doc.auto_review:
        return None
    if doc.status in (DocStatus.chunking, DocStatus.indexing):
        # Đang chunk/index: không chặn người sửa — ghi cờ (gộp các trang), job index xong sẽ chạy lại
        old = c.repo.s.get(FLAGS, doc_id, "reindex_pending")
        full = pages is None or (old is not None and old.get("pages") is None)
        merged = None if full else sorted(set(pages or []) | set((old or {}).get("pages") or []))
        c.repo.s.put(
            FLAGS, doc_id, "reindex_pending", {"id": "reindex_pending", "by": actor, "at": now_iso(), "pages": merged}
        )
        return None
    all_pages = c.repo.list_pages(doc_id)
    if not all_pages or any(p.status not in READY for p in all_pages):
        return None  # còn trang chưa qua nối trang / lỗi — luồng tự động sẽ chạy tiếp hoặc cần Retry
    pl.auto_approve_pages(c, doc_id)
    emit(c, doc_id, "auto.reindex", by=actor)
    pl.start_chunking(c, doc_id, actor, sorted({doc.book_page(n) for n in pages}) if pages else None)
    return None


def run_pending_reindex(c: Container, doc_id: str) -> None:
    """Gọi khi job index của tài liệu auto_review xong: có sửa trong lúc chạy thì chunk + index lại."""
    flag = c.repo.s.get(FLAGS, doc_id, "reindex_pending")
    if not flag:
        return None
    c.repo.s.delete(FLAGS, doc_id, "reindex_pending")
    reindex_document(c, doc_id, flag.get("by") or AUTO, flag.get("pages"))
    return None


def _after_change(c: Container, doc: Document, actor: str, pages: list[int]) -> None:
    """Nội dung trang (PDF) `pages` đã đổi: tài liệu tự chạy (auto_review) → chunk lại phần liên quan + index lại;
    duyệt tay → chunk cũ hết hiệu lực."""
    if doc.auto_review:
        try:
            reindex_document(c, doc.id, actor, pages)
        except pl.PipelineError as e:  # tài liệu đang bận → lần sửa sau sẽ index lại
            log.warning("inspect.reindex_skipped doc=%s code=%s", doc.id, e.code)
    else:
        pl._invalidate_chunks(c, doc.id)
        pl.refresh_doc(c, doc.id)


def edit_element(c: Container, doc_id: str, n: int, eid: str, text: str, actor: str) -> dict:
    doc, p = _doc(c, doc_id), _page(c, doc_id, n)
    _require_editable(c, doc, p)
    state = load_state(c, doc, p)
    e = _element(state, eid)
    before = f"{e.get('source')} {_fmt(e.get('confidence'))}"
    e.update(text=text.strip("\n"), status="fixed", source="manual", edited_by=actor, edited_at=now_iso())
    v = _commit(c, doc, p, state, "element_edit", actor, eid)
    _log(
        c,
        doc_id,
        n,
        {
            "at": e["edited_at"],
            "by": actor,
            "kind": "element_edit",
            "element_id": eid,
            "summary": f"{eid} · {before} → manual · v{v}",
        },
    )
    c.repo.audit(actor, "element.edit", f"{doc_id}:{n}", element=eid, v=v)
    _after_change(c, doc, actor, [n])
    return public(e)


def accept_element(c: Container, doc_id: str, n: int, eid: str, actor: str) -> dict:
    doc, p = _doc(c, doc_id), _page(c, doc_id, n)
    _require_editable(c, doc, p)
    state = load_state(c, doc, p)
    e = _element(state, eid)
    e.update(status="accepted", edited_by=actor, edited_at=now_iso())
    md_before = p.current_version
    v = _commit(c, doc, p, state, "element_edit", actor, eid)
    _log(
        c,
        doc_id,
        n,
        {
            "at": e["edited_at"],
            "by": actor,
            "kind": "element_accept",
            "element_id": eid,
            "summary": f"{eid} · accepted",
        },
    )
    c.repo.audit(actor, "element.accept", f"{doc_id}:{n}", element=eid, v=v)
    if v != md_before:
        _after_change(c, doc, actor, [n])
    return public(e)


def _llm(c: Container):
    try:
        return c.config.adapter("llm")
    except NotConfigured as e:
        raise InspectError("llm_not_configured") from e


def _parse_json(text: str) -> dict:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        data = json.loads(t)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def reread_guide(c: Container, override: str = "") -> str:
    """Hướng dẫn đọc lại dùng cho lần chạy này: người dùng nhập (nếu có) hoặc mặc định trong settings."""
    return override.strip() or _opts(c).quality.reread_prompt


def _vlm_read(llm, png: bytes, e: dict, prompt: str = "", guide: str = "") -> tuple[str, float | None]:
    user = f"Region type: {e['label']}\nCurrent text:\n{e.get('text') or e.get('raw_text') or '(empty)'}"
    if prompt:
        user += f"\n\nInstruction from reviewer:\n{prompt}"
    from app.domain.options import DEFAULT_REREAD_PROMPT

    res = llm.chat(
        [
            ChatMessage("system", reread_system(guide or DEFAULT_REREAD_PROMPT)),
            ChatMessage("user", user, [crop_png(png, e["bbox"])]),
        ],
        tier="vision",
        json_mode=True,
        max_tokens=4000,
    )
    data = _parse_json(res.text)
    md = data.get("markdown") if data else None
    if not isinstance(md, str):
        md = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", (res.text or "").strip())
    conf = data.get("confidence") if data else None
    try:
        conf = None if conf is None else round(max(0.0, min(1.0, float(conf))), 3)
    except (TypeError, ValueError):
        conf = None
    return md.strip("\n"), conf


def _apply_reread(e: dict, md: str, conf: float | None, actor: str, *, auto: bool) -> str:
    before = f"{e.get('source')} {_fmt(e.get('confidence'))}"
    if "reread_from" not in e:
        e["reread_from"] = e.get("confidence") if e.get("confidence") is not None else ""
    if e["label"] == "picture" and e.get("figure") is not None and f"figure:{e['figure']}" not in md:
        md = f"<!-- figure:{e['figure']} -->\n{md}"  # giữ chú thích hình để định vị lại được
    e.update(text=md, source="vlm", confidence=conf, edited_by=actor, edited_at=now_iso())
    if not auto:
        e["status"] = "fixed"
    return f"{e['id']} · {before} → vlm {_fmt(conf)}"


def reread_element(c: Container, doc_id: str, n: int, eid: str, prompt: str, actor: str) -> dict:
    doc, p = _doc(c, doc_id), _page(c, doc_id, n)
    _require_editable(c, doc, p)
    llm = _llm(c)
    state = load_state(c, doc, p)
    e = _element(state, eid)
    md, conf = _vlm_read(llm, _page_png(c, doc_id, n), e, prompt, reread_guide(c))
    summary = _apply_reread(e, md, conf, actor, auto=False)
    v = _commit(c, doc, p, state, "element_reread", actor, eid)
    _log(
        c,
        doc_id,
        n,
        {
            "at": e["edited_at"],
            "by": actor,
            "kind": "element_reread",
            "element_id": eid,
            "summary": f"{summary} · v{v}",
        },
    )
    c.repo.audit(actor, "element.reread", f"{doc_id}:{n}", element=eid, v=v)
    _after_change(c, doc, actor, [n])
    return public(e)


def weak_targets(c: Container, doc_id: str) -> list[tuple[int, str]]:
    doc = _doc(c, doc_id)
    out = []
    for p in sorted(c.repo.list_pages(doc_id), key=lambda x: x.page):
        if p.status not in READY:
            continue
        state = load_state(c, doc, p)
        out += [(p.page, e["id"]) for e in state["elements"] if e.get("status") == "weak"]
    return out


def fix_weak(
    c: Container, doc_id: str, actor: str, targets: list[tuple[int, str]] | None = None, prompt: str = ""
) -> int:
    """AI đọc lại mọi phần tử còn weak (người bấm 「弱点をAIで修正」 → status fixed). Trả số phần tử đã đọc lại.
    `prompt`: hướng dẫn người dùng sửa cho lần chạy này; rỗng → `quality.reread_prompt` trong settings."""
    doc = _doc(c, doc_id)
    llm = _llm(c)
    guide = reread_guide(c, prompt)
    targets = weak_targets(c, doc_id) if targets is None else targets
    by_page: dict[int, list[str]] = {}
    for n, eid in targets:
        by_page.setdefault(n, []).append(eid)
    done = 0
    touched: list[int] = []
    for n, eids in by_page.items():
        p = c.repo.get_page(doc_id, n)
        if not p or p.status not in READY:
            continue
        state = load_state(c, doc, p)
        png = _page_png(c, doc_id, n)
        changed = []
        for eid in eids:
            e = next((x for x in state["elements"] if x["id"] == eid), None)
            if e is None or e.get("status") != "weak":
                continue
            try:
                md, conf = _vlm_read(llm, png, e, guide=guide)
            except Exception as ex:  # noqa: BLE001 — một phần tử lỗi không chặn phần còn lại
                log.warning("inspect.fix_failed doc=%s page=%s element=%s error=%s", doc_id, n, eid, type(ex).__name__)
                continue
            changed.append(_apply_reread(e, md, conf, actor, auto=False))
        if not changed:
            continue
        v = _commit(c, doc, p, state, "element_reread", actor, "fix-weak")
        at = now_iso()
        for s in changed:
            eid = s.split(" ", 1)[0]
            _log(
                c,
                doc_id,
                n,
                {"at": at, "by": actor, "kind": "element_reread", "element_id": eid, "summary": f"{s} · v{v}"},
            )
        done += len(changed)
        touched.append(n)
    c.repo.audit(actor, "document.fix_weak", doc_id, elements=done, custom_prompt=bool(prompt.strip()))
    if done:
        _after_change(c, _doc(c, doc_id), actor, touched)
    return done


# ================================================================== chất lượng
def doc_quality(c: Container, doc_id: str, build: bool = False) -> dict | None:
    """DocQuality. Mặc định chỉ đọc phần tử đã lưu (rẻ, không gọi LLM — A1 dùng cho thẻ nguồn); chưa trang nào
    có phần tử → None. `build=True` (API) dựng lười các trang còn thiếu."""
    doc = c.repo.get_doc(doc_id)
    if not doc:
        return None
    q = _opts(c).quality
    pages = []
    counts: dict[str, int] = {}
    total = 0
    for p in sorted(c.repo.list_pages(doc_id), key=lambda x: x.page):
        if p.status not in READY:
            continue
        state = load_state(c, doc, p, build=build)
        if not state:
            continue
        open_n = 0
        for e in state["elements"]:
            total += len(e.get("weak") or [])
            for f in rules.open_flags(e):
                counts[f["code"]] = counts.get(f["code"], 0) + 1
                open_n += 1
        pages.append({"page": p.page, "score": state["score"], "grade": state["grade"], "weak_open": open_n})
    if not pages:
        return None
    score = rules.doc_quality_score([x["score"] for x in pages])
    worst = min(pages, key=lambda x: x["score"])
    return {
        "score": score,
        "grade": rules.quality_grade(score, q),
        "worst_page": {"page": worst["page"], "score": worst["score"], "grade": worst["grade"]},
        "counts": counts,
        "weak_total": total,
        "weak_open": sum(counts.values()),
        "pages": pages,
    }


def empty_quality() -> dict:
    return {"score": 0, "grade": "poor", "worst_page": None, "counts": {}, "weak_total": 0, "weak_open": 0, "pages": []}


def weak_items(c: Container, doc_id: str) -> list[dict]:
    doc = _doc(c, doc_id)
    out = []
    for p in sorted(c.repo.list_pages(doc_id), key=lambda x: x.page):
        if p.status not in READY:
            continue
        state = load_state(c, doc, p)
        for e in sorted(state["elements"], key=lambda x: x["order"]):
            preview = re.sub(r"\s+", " ", rules.visible_text(e.get("text") or "") or e.get("raw_text") or "")[:80]
            for f in e.get("weak") or []:
                out.append(
                    {
                        "page": p.page,
                        "element_id": e["id"],
                        "order": e["order"],
                        "label": e["label"],
                        "code": f["code"],
                        "severity": f["severity"],
                        "status": e["status"],
                        "preview": preview,
                    }
                )
    return out


def open_weak_pages(c, doc_id: str) -> set[int]:
    """Các trang PDF còn điểm yếu chưa sửa / xác nhận (A1 dùng để gắn ⚠ vào trích dẫn chat). Chỉ đọc phần tử đã lưu."""
    doc = c.repo.get_doc(doc_id)
    if not doc:
        return set()
    out = set()
    for p in c.repo.list_pages(doc_id):
        state = load_state(c, doc, p, build=False)
        if state and any(e.get("status") == "weak" for e in state.get("elements") or []):
            out.add(p.page)
    return out


def score_pages(c: Container, doc_id: str, pages: list[int] | None, actor: str) -> list[dict]:
    """VLM chấm (ảnh trang ↔ Markdown) tối đa 5 trang — mặc định 5 trang điểm thấp nhất. Điểm VLM được lưu và
    trộn vào điểm trang (trung bình) cho tới khi Markdown của trang đổi."""
    doc = _doc(c, doc_id)
    llm = _llm(c)
    q = _opts(c).quality
    if not pages:
        quality = doc_quality(c, doc_id, build=True) or empty_quality()
        pages = [x["page"] for x in sorted(quality["pages"], key=lambda x: (x["score"], x["page"]))]
    out = []
    for n in list(dict.fromkeys(pages))[:SCORE_MAX_PAGES]:
        p = c.repo.get_page(doc_id, n)
        if not p or p.status not in READY:
            continue
        state = load_state(c, doc, p)
        md = pl.page_markdown(c, p)
        res = llm.chat(
            [
                ChatMessage("system", SCORE_PROMPT),
                ChatMessage("user", f"Extracted Markdown:\n{md[:12000]}", [_page_png(c, doc_id, n)]),
            ],
            tier="vision",
            json_mode=True,
            max_tokens=500,
        )
        data = _parse_json(res.text)
        try:
            score = int(round(max(0.0, min(100.0, float(data.get("score"))))))
        except (TypeError, ValueError):
            continue
        comment = str(data.get("comment") or "")[:500]
        state["vlm"] = {"score": score, "comment": comment, "at": now_iso(), "md_version": state["md_version"]}
        assess(c, doc, p, state)
        _save_state(c, doc_id, n, state)
        out.append({"page": n, "score": score, "grade": rules.quality_grade(score, q), "comment": comment})
    c.repo.audit(actor, "document.score", doc_id, pages=[x["page"] for x in out])
    return out


def prepare_document(c, doc_id: str) -> None:
    """Gọi trong luồng tự động (sau nối trang, trước khi tự duyệt): dựng phần tử cho mọi trang, tự gọi VLM đọc lại
    phần tử có confidence dưới `quality.auto_vlm_below` (đánh dấu `reread`, vẫn chờ người xác nhận), tính chất
    lượng. Lỗi dựng phần tử của một trang được ném ra (bước auto_review ghi `auto.prepare_failed`)."""
    doc = _doc(c, doc_id)
    q = _opts(c).quality
    guide = q.reread_prompt
    try:
        llm = c.config.adapter("llm")
    except NotConfigured:
        llm = None
    for p in sorted(c.repo.list_pages(doc_id), key=lambda x: x.page):
        if p.status not in READY:
            continue
        state = load_state(c, doc, p)
        if llm is None:
            continue
        low = [
            e
            for e in state["elements"]
            if e.get("confidence") is not None
            and float(e["confidence"]) < q.auto_vlm_below
            and e.get("status") not in rules.DONE_STATUSES
            and "reread_from" not in e
            and e["label"] not in rules.HEADER_FOOTER
        ][:AUTO_REREAD_MAX_PER_PAGE]
        if not low:
            continue
        png = _page_png(c, doc_id, p.page)
        changed = []
        for e in low:
            try:
                md, conf = _vlm_read(llm, png, e, guide=guide)
            except Exception as ex:  # noqa: BLE001 — VLM lỗi: giữ bản đọc cũ, phần tử vẫn weak
                log.warning(
                    "inspect.auto_reread_failed doc=%s page=%s element=%s error=%s",
                    doc_id,
                    p.page,
                    e["id"],
                    type(ex).__name__,
                )
                continue
            changed.append(_apply_reread(e, md, conf, AUTO, auto=True))
        if changed:
            v = _commit(c, doc, p, state, "element_reread", AUTO, "auto")
            at = now_iso()
            for s in changed:
                eid = s.split(" ", 1)[0]
                _log(
                    c,
                    doc_id,
                    p.page,
                    {"at": at, "by": AUTO, "kind": "element_reread", "element_id": eid, "summary": f"{s} · v{v}"},
                )


# ================================================================== thông tin / văn bản / insights / chunk
def _language(text: str) -> str:
    sample = re.sub(r"\s+", "", text)[:4000]
    if not sample:
        return ""
    cjk = sum(1 for ch in sample if unicodedata.name(ch, "").startswith(("CJK", "HIRAGANA", "KATAKANA")))
    if cjk / len(sample) > 0.1:
        return "ja"
    viet = sum(1 for ch in sample if ch in "ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ")
    return "vi" if viet > 3 else "en"


def doc_info(c: Container, doc_id: str) -> dict:
    doc = _doc(c, doc_id)
    pages = sorted(c.repo.list_pages(doc_id), key=lambda x: x.page)
    sample = "\n".join(pl.page_markdown(c, p) for p in pages[:3])
    size = doc.size_bytes
    if not size and c.blob.exists(k_source(doc_id)):
        size = len(c.blob.get(k_source(doc_id)))
    return {
        "doc_id": doc.id,
        "name": doc.name,
        "filename": doc.filename,
        "file_type": doc.file_type if doc.file_type in ("pdf", "image") else "pdf",
        "language": _language(sample),
        "pages": doc.n_pages,
        "size_bytes": size,
        "created_at": doc.created_at,
        "created_by": doc.created_by,
        "origin": "upload",
        "mode": "full",
        "status": doc.status.value,
    }


def doc_text(c: Container, doc_id: str) -> list[dict]:
    _doc(c, doc_id)
    return [
        {"page": p.page, "book_page": p.book_page, "markdown": pl.page_markdown(c, p)}
        for p in sorted(c.repo.list_pages(doc_id), key=lambda x: x.page)
    ]


def _k_insights(doc_id: str) -> str:
    return f"docs/{doc_id}/insights.json"


def get_insights(c: Container, doc_id: str) -> dict | None:
    _doc(c, doc_id)
    return _json(c, _k_insights(doc_id))


def generate_insights(c: Container, doc_id: str, actor: str) -> dict:
    doc = _doc(c, doc_id)
    llm = _llm(c)
    text = "\n\n".join(f"[p.{x['page']}]\n{x['markdown']}" for x in doc_text(c, doc_id))
    if not rules.norm_text(text):
        raise InspectError("no_text")
    res = llm.chat(
        [ChatMessage("system", INSIGHTS_PROMPT), ChatMessage("user", f"Document: {doc.name}\n\n{text[:24000]}")],
        json_mode=True,
        max_tokens=1500,
    )
    data = _parse_json(res.text)
    points = data.get("key_points") if isinstance(data.get("key_points"), list) else []
    out = {
        "summary": str(data.get("summary") or "").strip(),
        "key_points": [str(x).strip() for x in points if str(x).strip()][:10],
        "generated_at": now_iso(),
    }
    if not out["summary"] and not out["key_points"]:
        raise InspectError("insights_failed")
    _put_json(c, _k_insights(doc_id), out)
    c.repo.audit(actor, "document.insights", doc_id)
    return out


def page_chunks(c: Container, doc_id: str, n: int) -> list[dict]:
    """Chunk phủ trang PDF n (chunk lưu trang SÁCH → đổi bằng doc.book_page)."""
    doc = _doc(c, doc_id)
    _page(c, doc_id, n)
    book = doc.book_page(n)
    return [
        x.model_dump(mode="json")
        for x in sorted(c.repo.list_chunks(doc_id), key=lambda x: x.seq)
        if x.page_from <= book <= x.page_to
    ]
