"""Tài liệu, trang (review OCR), chunk (review chunk), tìm thử."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import admin, container, reviewer, viewer
from app.domain.models import User
from app.services import chunks as chunk_svc
from app.services import pipeline as pl
from app.services.container import Container
from app.steps import rules
from app.steps.common import k_page, k_source, k_version

router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_UPLOAD = 200 * 1024 * 1024


def _doc(c: Container, doc_id: str):
    d = c.repo.get_doc(doc_id)
    if not d:
        raise HTTPException(404, {"code": "doc_not_found"})
    return d


@router.get("")
def list_documents(c: Container = Depends(container), _: User = Depends(viewer)):
    return [d.model_dump(mode="json") for d in c.repo.list_docs()]


@router.post("")
async def upload(
    file: UploadFile = File(...),
    name: str = Form(""),
    kind: str = Form("other"),
    book_page_start: int = Form(1),
    page_from: int | None = Form(None),
    page_to: int | None = Form(None),
    c: Container = Depends(container),
    user: User = Depends(reviewer),
):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, {"code": "too_large"})
    doc = pl.create_document(
        c,
        data=data,
        filename=file.filename or "upload.pdf",
        name=name,
        kind=kind,
        book_page_start=book_page_start,
        page_from=page_from,
        page_to=page_to,
        actor=user.email,
        auto_review=c.config.pipeline()[1].review.auto_review,
    )
    return doc.model_dump(mode="json")


@router.get("/{doc_id}")
def get_document(doc_id: str, c: Container = Depends(container), _: User = Depends(viewer)):
    return pl.refresh_doc(c, _doc(c, doc_id)).model_dump(mode="json")


class DocPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None


@router.patch("/{doc_id}")
def patch_document(doc_id: str, body: DocPatch, c: Container = Depends(container), user: User = Depends(reviewer)):
    doc = _doc(c, doc_id)
    if body.name is not None and body.name.strip() and body.name.strip() != doc.name:
        doc.name = body.name.strip()
        c.repo.save_doc(doc)
        c.repo.audit(user.email, "doc.rename", doc_id)  # không ghi tên vào log, chỉ id
    if body.enabled is not None:
        doc = pl.set_enabled(c, doc_id, body.enabled, user.email)
    return doc.model_dump(mode="json")


@router.delete("/{doc_id}")
def delete_document(doc_id: str, c: Container = Depends(container), user: User = Depends(admin)):
    _doc(c, doc_id)
    pl.delete_document(c, doc_id, user.email)
    return {"ok": True}


@router.get("/{doc_id}/source")
def source_pdf(doc_id: str, c: Container = Depends(container), _: User = Depends(viewer)):
    _doc(c, doc_id)
    return Response(c.blob.get(k_source(doc_id)), media_type="application/pdf")


@router.post("/{doc_id}/actions/{action}")
def action(doc_id: str, action: str, c: Container = Depends(container), user: User = Depends(reviewer)):
    _doc(c, doc_id)
    from app.services.jobs import enqueue

    if action == "start_chunking":
        job = pl.start_chunking(c, doc_id, user.email)
    elif action == "index":
        job = pl.start_index(c, doc_id, user.email)
    elif action == "restitch":
        job = enqueue(c, doc_id, "stitch", actor=user.email)
    elif action == "retry_failed":
        n = 0
        for p in c.repo.list_pages(doc_id):
            if p.status.value == "failed":
                pl.reprocess_page(c, doc_id, p.page, user.email)
                n += 1
        return {"retried": n}
    else:
        raise HTTPException(404, {"code": "unknown_action"})
    return {"job": job.model_dump(mode="json") if job else None}


# ------------------------------------------------------------------ trang
@router.get("/{doc_id}/pages")
def list_pages(doc_id: str, c: Container = Depends(container), _: User = Depends(viewer)):
    _doc(c, doc_id)
    return [p.model_dump(mode="json") for p in c.repo.list_pages(doc_id)]


def _page(c: Container, doc_id: str, page: int):
    p = c.repo.get_page(doc_id, page)
    if not p:
        raise HTTPException(404, {"code": "page_not_found"})
    return p


@router.get("/{doc_id}/pages/{page}")
def get_page(doc_id: str, page: int, c: Container = Depends(container), _: User = Depends(viewer)):
    p = _page(c, doc_id, page)
    sources = {}
    for name in ("docling", "cu", "stitched"):
        key = k_page(doc_id, page, f"{name}.md")
        if c.blob.exists(key):
            sources[name] = c.blob.get(key).decode()
    meta = _raw_json(c, doc_id, page, "docling") or {}
    threshold = c.config.pipeline()[1].review.low_confidence
    return {
        **p.model_dump(mode="json"),
        "markdown": pl.page_markdown(c, p),
        "sources": sources,
        "elements": meta.get("elements", []),
        "image_size": meta.get("image_size"),
        # Vùng confidence thấp (Docling + CU) để viền đỏ — chỉ để tô màu, không bỏ qua review
        "low_confidence": {
            "threshold": threshold,
            "boxes": rules.low_confidence_boxes(meta, _raw_json(c, doc_id, page, "cu"), threshold),
        },
    }


RAW_SOURCES = ("docling", "cu")


def _raw_json(c: Container, doc_id: str, page: int, name: str) -> dict | None:
    key = k_page(doc_id, page, f"{name}.json")
    if not c.blob.exists(key):
        return None
    try:
        return json.loads(c.blob.get(key))
    except ValueError:
        return None


@router.get("/{doc_id}/pages/{page}/raw/{name}")
def get_page_raw(doc_id: str, page: int, name: str, c: Container = Depends(container), _: User = Depends(viewer)):
    """Kết quả thô của Docling (`docling.json`) hoặc Content Understanding (`cu.json`) cho tab JSON."""
    _page(c, doc_id, page)
    if name not in RAW_SOURCES:
        raise HTTPException(404, {"code": "raw_not_found"})
    key = k_page(doc_id, page, f"{name}.json")
    if not c.blob.exists(key):
        raise HTTPException(404, {"code": "raw_not_found"})
    return Response(c.blob.get(key), media_type="application/json")


@router.get("/{doc_id}/pages/{page}/image")
def page_image(doc_id: str, page: int, c: Container = Depends(container), _: User = Depends(viewer)):
    key = k_page(doc_id, page, "image.png")
    if not c.blob.exists(key):
        raise HTTPException(404, {"code": "image_not_ready"})
    return Response(c.blob.get(key), media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@router.get("/{doc_id}/pages/{page}/versions/{v}")
def page_version(doc_id: str, page: int, v: int, c: Container = Depends(container), _: User = Depends(viewer)):
    key = k_version(doc_id, page, v)
    if not c.blob.exists(key):
        raise HTTPException(404, {"code": "version_not_found"})
    return {"v": v, "markdown": c.blob.get(key).decode()}


class ContentIn(BaseModel):
    markdown: str
    note: str = ""


class SubmitIn(BaseModel):
    markdown: str | None = None


class RerunIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)


class RouteIn(BaseModel):
    override: str


@router.put("/{doc_id}/pages/{page}/content")
def save_content(
    doc_id: str, page: int, body: ContentIn, c: Container = Depends(container), user: User = Depends(reviewer)
):
    return pl.edit_page(c, doc_id, page, body.markdown, user.email, body.note).model_dump(mode="json")


@router.post("/{doc_id}/pages/{page}/submit")
def submit(doc_id: str, page: int, body: SubmitIn, c: Container = Depends(container), user: User = Depends(reviewer)):
    return pl.submit_page(c, doc_id, page, user.email, body.markdown).model_dump(mode="json")


@router.post("/{doc_id}/pages/{page}/reopen")
def reopen(doc_id: str, page: int, c: Container = Depends(container), user: User = Depends(reviewer)):
    return pl.reopen_page(c, doc_id, page, user.email).model_dump(mode="json")


@router.post("/{doc_id}/pages/{page}/restore/{v}")
def restore(doc_id: str, page: int, v: int, c: Container = Depends(container), user: User = Depends(reviewer)):
    return pl.restore_version(c, doc_id, page, v, user.email).model_dump(mode="json")


@router.post("/{doc_id}/pages/{page}/rerun")
def rerun(doc_id: str, page: int, body: RerunIn, c: Container = Depends(container), user: User = Depends(reviewer)):
    job = pl.rerun_page_llm(c, doc_id, page, body.prompt, user.email)
    return {"job": job.model_dump(mode="json") if job else None}


@router.post("/{doc_id}/pages/{page}/route")
def route_override(
    doc_id: str, page: int, body: RouteIn, c: Container = Depends(container), user: User = Depends(reviewer)
):
    return pl.set_route_override(c, doc_id, page, body.override, user.email).model_dump(mode="json")


@router.post("/{doc_id}/pages/{page}/reprocess")
def reprocess(doc_id: str, page: int, c: Container = Depends(container), user: User = Depends(reviewer)):
    return pl.reprocess_page(c, doc_id, page, user.email).model_dump(mode="json")


# ------------------------------------------------------------------ chunk
@router.get("/{doc_id}/chunks")
def list_chunks(doc_id: str, c: Container = Depends(container), _: User = Depends(viewer)):
    _doc(c, doc_id)
    return [x.model_dump(mode="json") for x in c.repo.list_chunks(doc_id)]


class ChunkIn(BaseModel):
    text: str
    item_code: str = ""
    title: str = ""
    page_from: int | None = None
    page_to: int | None = None


class IdsIn(BaseModel):
    ids: list[str]
    approved: bool = True


class SplitIn(BaseModel):
    offset: int


@router.put("/{doc_id}/chunks/{chunk_id}")
def update_chunk(
    doc_id: str, chunk_id: str, body: ChunkIn, c: Container = Depends(container), user: User = Depends(reviewer)
):
    return chunk_svc.update_chunk(
        c,
        doc_id,
        chunk_id,
        text=body.text,
        item_code=body.item_code,
        title=body.title,
        page_from=body.page_from,
        page_to=body.page_to,
        actor=user.email,
    ).model_dump(mode="json")


@router.post("/{doc_id}/chunks/merge")
def merge(doc_id: str, body: IdsIn, c: Container = Depends(container), user: User = Depends(reviewer)):
    return chunk_svc.merge_chunks(c, doc_id, body.ids, user.email).model_dump(mode="json")


@router.post("/{doc_id}/chunks/{chunk_id}/split")
def split(doc_id: str, chunk_id: str, body: SplitIn, c: Container = Depends(container), user: User = Depends(reviewer)):
    return [x.model_dump(mode="json") for x in chunk_svc.split_chunk(c, doc_id, chunk_id, body.offset, user.email)]


@router.post("/{doc_id}/chunks/approve")
def approve(doc_id: str, body: IdsIn, c: Container = Depends(container), user: User = Depends(reviewer)):
    return {"changed": chunk_svc.approve_chunks(c, doc_id, body.ids, body.approved, user.email)}
