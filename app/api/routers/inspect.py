"""UI v2 — Kiểm tra tài liệu (検査): phần tử theo thứ tự đọc, chất lượng, điểm yếu, sửa / đọc lại. Chủ: backend A2.
Hợp đồng: docs/UI_V2_SPEC.md + web/src/lib/v2types.ts. Xem = viewer, ghi = reviewer."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import container, reviewer, viewer
from app.domain.models import User
from app.services import inspect as svc
from app.services.container import Container

router = APIRouter(prefix="/api/documents", tags=["inspect"])

NOT_FOUND = {"doc_not_found", "page_not_found", "element_not_found"}


def _call(fn: Callable[..., Any], *args, **kwargs) -> Any:
    """Lỗi 'không tìm thấy' → 404; lỗi nghiệp vụ khác để handler PipelineError trả 409."""
    try:
        return fn(*args, **kwargs)
    except svc.InspectError as e:
        if e.code in NOT_FOUND:
            raise HTTPException(404, {"code": e.code}) from e
        raise


def _read(fn: Callable[..., Any], *args, **kwargs) -> Any:
    """Như `_call` cho GET: trang chưa có nội dung (page_not_ready) cũng trả 404 — UI hiện 「処理中です」."""
    try:
        return _call(fn, *args, **kwargs)
    except svc.InspectError as e:
        if e.code == "page_not_ready":
            raise HTTPException(404, {"code": e.code}) from e
        raise


class TextIn(BaseModel):
    text: str = Field(max_length=100_000)


class RereadIn(BaseModel):
    prompt: str = Field(default="", max_length=2000)


class FixWeakIn(BaseModel):
    prompt: str = Field(default="", max_length=svc.REREAD_MAX)


class ScoreIn(BaseModel):
    pages: list[int] | None = None


# ------------------------------------------------------------------ tài liệu
@router.get("/{doc_id}/info")
def info(doc_id: str, c: Container = Depends(container), _: User = Depends(viewer)):
    return _call(svc.doc_info, c, doc_id)


@router.get("/{doc_id}/text")
def text(doc_id: str, c: Container = Depends(container), _: User = Depends(viewer)):
    return _call(svc.doc_text, c, doc_id)


@router.get("/{doc_id}/insights")
def get_insights(doc_id: str, c: Container = Depends(container), _: User = Depends(viewer)):
    data = _call(svc.get_insights, c, doc_id)
    if data is None:
        raise HTTPException(404, {"code": "no_insights"})
    return data


@router.post("/{doc_id}/insights")
def make_insights(doc_id: str, c: Container = Depends(container), user: User = Depends(reviewer)):
    return _call(svc.generate_insights, c, doc_id, user.email)


@router.get("/{doc_id}/quality")
def quality(doc_id: str, c: Container = Depends(container), _: User = Depends(viewer)):
    if c.repo.get_doc(doc_id) is None:
        raise HTTPException(404, {"code": "doc_not_found"})
    return svc.doc_quality(c, doc_id, build=True) or svc.empty_quality()


@router.get("/{doc_id}/weak")
def weak(doc_id: str, c: Container = Depends(container), _: User = Depends(viewer)):
    return _call(svc.weak_items, c, doc_id)


@router.get("/{doc_id}/fix-weak")
def fix_weak_info(doc_id: str, c: Container = Depends(container), _: User = Depends(viewer)):
    """Cho hộp thoại 「弱点をAIで修正」: hướng dẫn mặc định (settings) + số phần tử sẽ đọc lại."""
    targets = _call(svc.weak_targets, c, doc_id)
    return {"prompt": svc.reread_guide(c), "weak": len(targets)}


@router.post("/{doc_id}/fix-weak")
def fix_weak(
    doc_id: str,
    tasks: BackgroundTasks,
    body: FixWeakIn | None = None,
    c: Container = Depends(container),
    user: User = Depends(reviewer),
):
    """Đọc lại mọi phần tử weak bằng VLM — chạy nền sau khi trả lời (PoC: trong tiến trình API).
    `prompt` rỗng → dùng `quality.reread_prompt` trong settings."""
    _call(svc._llm, c)
    targets = _call(svc.weak_targets, c, doc_id)
    if targets:
        tasks.add_task(svc.fix_weak, c, doc_id, user.email, targets, body.prompt if body else "")
    return {"queued": len(targets)}


@router.post("/{doc_id}/score")
def score(doc_id: str, body: ScoreIn | None = None, c: Container = Depends(container), user: User = Depends(reviewer)):
    return {"scored": _call(svc.score_pages, c, doc_id, (body.pages if body else None), user.email)}


# ------------------------------------------------------------------ trang & phần tử
@router.get("/{doc_id}/pages/{page}/elements")
def page_elements(doc_id: str, page: int, c: Container = Depends(container), _: User = Depends(viewer)):
    return _read(svc.page_elements, c, doc_id, page)


@router.get("/{doc_id}/pages/{page}/elements/{eid}/image")
def element_image(doc_id: str, page: int, eid: str, c: Container = Depends(container), _: User = Depends(viewer)):
    png = _read(svc.element_image, c, doc_id, page, eid)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})


@router.get("/{doc_id}/pages/{page}/elements/{eid}/raw")
def element_raw(doc_id: str, page: int, eid: str, c: Container = Depends(container), _: User = Depends(viewer)):
    return _read(svc.element_raw, c, doc_id, page, eid)


@router.put("/{doc_id}/pages/{page}/elements/{eid}")
def edit_element(
    doc_id: str, page: int, eid: str, body: TextIn, c: Container = Depends(container), user: User = Depends(reviewer)
):
    return _call(svc.edit_element, c, doc_id, page, eid, body.text, user.email)


@router.post("/{doc_id}/pages/{page}/elements/{eid}/reread")
def reread_element(
    doc_id: str,
    page: int,
    eid: str,
    body: RereadIn | None = None,
    c: Container = Depends(container),
    user: User = Depends(reviewer),
):
    return _call(svc.reread_element, c, doc_id, page, eid, body.prompt if body else "", user.email)


@router.post("/{doc_id}/pages/{page}/elements/{eid}/accept")
def accept_element(doc_id: str, page: int, eid: str, c: Container = Depends(container), user: User = Depends(reviewer)):
    return _call(svc.accept_element, c, doc_id, page, eid, user.email)


@router.get("/{doc_id}/pages/{page}/chunks")
def page_chunks(doc_id: str, page: int, c: Container = Depends(container), _: User = Depends(viewer)):
    return _call(svc.page_chunks, c, doc_id, page)


@router.get("/{doc_id}/pages/{page}/history")
def page_history(doc_id: str, page: int, c: Container = Depends(container), _: User = Depends(viewer)):
    return _call(svc.page_history, c, doc_id, page)
