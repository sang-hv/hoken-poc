"""UI v2 — Sổ tay (ライブラリ / ノートブック): nguồn, ghi chú, chat Agentic RAG. Chủ: backend A1.
Hợp đồng: docs/UI_V2_SPEC.md + web/src/lib/v2types.ts."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import container, reviewer, viewer
from app.domain.models import User
from app.services import notebooks as svc
from app.services.container import Container

router = APIRouter(prefix="/api", tags=["notebooks"])

MAX_UPLOAD = 200 * 1024 * 1024


def _nb(c: Container, nb_id: str) -> dict:
    nb = svc.get_notebook(c, nb_id)
    if not nb:
        raise HTTPException(404, {"code": "notebook_not_found"})
    return nb


def _member(c: Container, nb_id: str, doc_id: str) -> dict:
    m = svc.get_membership(c, nb_id, doc_id)
    if not m or not c.repo.get_doc(doc_id):
        raise HTTPException(404, {"code": "source_not_found"})
    return m


def _note(c: Container, nb_id: str, note_id: str) -> dict:
    n = c.repo.s.get(svc.NOTES, nb_id, note_id)
    if not n:
        raise HTTPException(404, {"code": "note_not_found"})
    return n


class NotebookIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class SourcePatch(BaseModel):
    enabled: bool


class NoteIn(BaseModel):
    title: str = Field(default="", max_length=200)
    text: str = Field(min_length=1, max_length=20000)


class NotePatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, min_length=1, max_length=20000)


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=8000)


class ChatIn(BaseModel):
    q: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    mode: Literal["auto", "deep"] = "auto"
    lang: Literal["auto", "ja", "en", "vi"] = "auto"


# ------------------------------------------------------------------ sổ tay
@router.get("/notebooks")
def list_notebooks(c: Container = Depends(container), _: User = Depends(viewer)):
    return svc.list_notebooks(c)


@router.post("/notebooks")
def create_notebook(body: NotebookIn, c: Container = Depends(container), user: User = Depends(reviewer)):
    if not body.name.strip():
        raise HTTPException(400, {"code": "name_required"})
    return svc.summary(c, svc.create_notebook(c, body.name, user.email))


@router.get("/notebooks/{nb_id}")
def get_notebook(nb_id: str, c: Container = Depends(container), _: User = Depends(viewer)):
    return svc.detail(c, _nb(c, nb_id))


@router.patch("/notebooks/{nb_id}")
def rename_notebook(nb_id: str, body: NotebookIn, c: Container = Depends(container), user: User = Depends(reviewer)):
    nb = _nb(c, nb_id)
    if not body.name.strip():
        raise HTTPException(400, {"code": "name_required"})
    return svc.summary(c, svc.rename_notebook(c, nb, body.name, user.email))


@router.delete("/notebooks/{nb_id}")
def delete_notebook(nb_id: str, c: Container = Depends(container), user: User = Depends(reviewer)):
    svc.delete_notebook(c, _nb(c, nb_id), user.email)
    return {"ok": True}


# ------------------------------------------------------------------ nguồn
@router.post("/notebooks/{nb_id}/sources")
async def upload_source(
    nb_id: str,
    file: UploadFile = File(...),
    name: str = Form(""),
    c: Container = Depends(container),
    user: User = Depends(reviewer),
):
    nb = _nb(c, nb_id)
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, {"code": "too_large"})
    if not data:
        raise HTTPException(400, {"code": "empty_file"})
    return svc.add_source(c, nb, data=data, filename=file.filename or "upload", name=name, actor=user.email)


@router.patch("/notebooks/{nb_id}/sources/{doc_id}")
def patch_source(
    nb_id: str, doc_id: str, body: SourcePatch, c: Container = Depends(container), user: User = Depends(reviewer)
):
    nb = _nb(c, nb_id)
    return svc.set_source_enabled(c, nb, _member(c, nb_id, doc_id), body.enabled, user.email)


@router.delete("/notebooks/{nb_id}/sources/{doc_id}")
def delete_source(nb_id: str, doc_id: str, c: Container = Depends(container), user: User = Depends(reviewer)):
    nb = _nb(c, nb_id)
    if not svc.get_membership(c, nb_id, doc_id):
        raise HTTPException(404, {"code": "source_not_found"})
    svc.remove_source(c, nb, doc_id, user.email)
    return {"ok": True}


# ------------------------------------------------------------------ ghi chú
@router.post("/notebooks/{nb_id}/notes")
def create_note(nb_id: str, body: NoteIn, c: Container = Depends(container), user: User = Depends(reviewer)):
    return svc.create_note(c, _nb(c, nb_id), body.title, body.text, user.email)


@router.patch("/notebooks/{nb_id}/notes/{note_id}")
def update_note(
    nb_id: str, note_id: str, body: NotePatch, c: Container = Depends(container), _: User = Depends(reviewer)
):
    nb = _nb(c, nb_id)
    return svc.update_note(c, nb, _note(c, nb_id, note_id), body.title, body.text)


@router.delete("/notebooks/{nb_id}/notes/{note_id}")
def delete_note(nb_id: str, note_id: str, c: Container = Depends(container), _: User = Depends(reviewer)):
    nb = _nb(c, nb_id)
    _note(c, nb_id, note_id)
    svc.delete_note(c, nb, note_id)
    return {"ok": True}


# ------------------------------------------------------------------ chat
@router.post("/notebooks/{nb_id}/chat")
def chat(nb_id: str, body: ChatIn, c: Container = Depends(container), _: User = Depends(reviewer)):
    _nb(c, nb_id)
    return svc.chat(c, nb_id, body.q, [t.model_dump() for t in body.history], body.mode, body.lang)
