"""Cài đặt (lớp 2: trạng thái dịch vụ AI cho cảnh báo ở dashboard; lớp 4: tuỳ chọn pipeline),
người dùng, audit, hệ thống, tìm thử. SSO đặt bằng env, không có API xem."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field, ValidationError

from app.api.deps import admin, container, current_user, reviewer, viewer
from app.core.util import hash_password, new_id, now_iso
from app.domain.models import Role, User
from app.domain.options import editable_dump
from app.services.container import Container

router = APIRouter(prefix="/api", tags=["admin"])


# ------------------------------------------------------------------ hệ thống (lớp 1, chỉ đọc)
@router.get("/system")
def system(c: Container = Depends(container), _: User = Depends(viewer)):
    health = {}
    for name, fn in (
        ("db", c.repo.s.health),
        ("queue", lambda: c.queue.depth("light")),
        ("blob", lambda: c.blob.exists("healthcheck")),
    ):
        t0 = time.monotonic()
        try:
            fn()
            health[name] = {"ok": True, "ms": int((time.monotonic() - t0) * 1000)}
        except Exception as e:  # noqa: BLE001
            health[name] = {"ok": False, "error": str(e)[:200]}
    return {"bootstrap": c.settings.public_summary(), "health": health}


# ------------------------------------------------------------------ lớp 2: provider (từ env, chỉ xem)
@router.get("/settings/providers")
def get_providers(c: Container = Depends(container), _: User = Depends(admin)):
    return c.config.providers_public()


@router.post("/settings/providers/{component}/test")
def test_provider(component: str, c: Container = Depends(container), _: User = Depends(admin)):
    from app.services.config_service import ENV_PREFIX, NotConfigured

    if component not in ENV_PREFIX:
        raise HTTPException(404, {"code": "unknown_adapter"})
    t0 = time.monotonic()
    try:
        c.config.build(component).health()
    except NotConfigured as e:
        return {"ok": False, "config_error": e.public()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
    return {"ok": True, "ms": int((time.monotonic() - t0) * 1000)}


# ------------------------------------------------------------------ lớp 4: pipeline
@router.get("/settings/pipeline")
def get_pipeline(c: Container = Depends(container), _: User = Depends(viewer)):
    v, opts = c.config.pipeline()
    d = c.repo.get_setting("pipeline") or {}
    return {
        "version": v,
        "options": editable_dump(opts),  # chỉ mục Admin chỉnh được; còn lại cố định trong code
        "updated_by": d.get("updated_by", ""),
        "updated_at": d.get("updated_at", ""),
    }


@router.put("/settings/pipeline")
def put_pipeline(body: dict, c: Container = Depends(container), user: User = Depends(admin)):
    try:
        v, opts = c.config.update_pipeline(body.get("options", body), user.email)
    except ValidationError as e:
        raise HTTPException(422, {"code": "invalid"}) from e
    return {"version": v, "options": editable_dump(opts)}


# ------------------------------------------------------------------ người dùng
class UserIn(BaseModel):
    email: EmailStr
    name: str = ""
    role: Role = Role.viewer
    password: str | None = Field(default=None, min_length=10)


class UserPatch(BaseModel):
    name: str | None = None
    role: Role | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=10)


@router.get("/users")
def list_users(c: Container = Depends(container), _: User = Depends(admin)):
    return [u.public() for u in c.repo.list_users()]


@router.post("/users")
def create_user(body: UserIn, c: Container = Depends(container), user: User = Depends(admin)):
    if c.repo.find_user_by_email(body.email):
        raise HTTPException(409, {"code": "email_exists"})
    u = User(
        id=new_id(),
        email=body.email,
        name=body.name,
        role=body.role,
        created_at=now_iso(),
        password_hash=hash_password(body.password) if body.password else "",
        provider="local" if body.password else "sso",
    )
    c.repo.save_user(u)
    c.repo.audit(user.email, "user.create", u.id, email=u.email, role=u.role.value)
    return u.public()


@router.patch("/users/{user_id}")
def patch_user(user_id: str, body: UserPatch, c: Container = Depends(container), user: User = Depends(admin)):
    u = c.repo.get_user(user_id)
    if not u:
        raise HTTPException(404, {"code": "user_not_found"})
    if u.id == user.id and (body.role not in (None, Role.admin) or body.active is False):
        raise HTTPException(409, {"code": "cannot_demote_self"})
    if body.name is not None:
        u.name = body.name
    if body.role is not None:
        u.role = body.role
    if body.active is not None:
        u.active = body.active
    if body.password:
        u.password_hash = hash_password(body.password)
    c.repo.save_user(u)
    c.repo.audit(user.email, "user.update", u.id, role=u.role.value, active=u.active)
    return u.public()


@router.delete("/users/{user_id}")
def delete_user(user_id: str, c: Container = Depends(container), user: User = Depends(admin)):
    if user_id == user.id:
        raise HTTPException(409, {"code": "cannot_delete_self"})
    c.repo.delete_user(user_id)
    c.repo.audit(user.email, "user.delete", user_id)
    return {"ok": True}


class PasswordIn(BaseModel):
    current: str
    new: str = Field(min_length=10)


@router.post("/me/password")
def change_password(body: PasswordIn, c: Container = Depends(container), user: User = Depends(current_user)):
    from app.core.util import verify_password

    if not user.password_hash or not verify_password(body.current, user.password_hash):
        raise HTTPException(400, {"code": "bad_credentials"})
    user.password_hash = hash_password(body.new)
    c.repo.save_user(user)
    return {"ok": True}


# ------------------------------------------------------------------ audit
AUDIT_SCAN = 5000  # số bản ghi gần nhất được lọc/phân trang (PoC; cần truy vấn phía DB nếu nhiều hơn)


@router.get("/audit")
def audit(
    q: str = "",
    limit: int = Query(300, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    paged: bool = False,
    c: Container = Depends(container),
    _: User = Depends(admin),
):
    """`q` khớp người thực hiện / hành động / đối tượng. `paged=true` trả {items, total}."""
    entries = c.repo.list_audit(AUDIT_SCAN if (paged or q) else limit)
    if q.strip():
        needle = q.strip().lower()
        entries = [a for a in entries if needle in f"{a.actor} {a.action} {a.target}".lower()]
    items = [a.model_dump(mode="json") for a in entries[offset : offset + limit]]
    return {"items": items, "total": len(entries)} if paged else items


# ------------------------------------------------------------------ tìm thử
class SearchIn(BaseModel):
    q: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=5, ge=1, le=50)


@router.post("/search")
def search(body: SearchIn, c: Container = Depends(container), _: User = Depends(reviewer)):
    from app.services.config_service import NotConfigured

    try:
        embedder, idx = c.config.adapter("embedding"), c.config.adapter("search")
    except NotConfigured as e:
        raise HTTPException(409, {"code": f"{e.component}_not_configured"}) from e
    t0 = time.monotonic()
    vec = embedder.embed([body.q])[0]
    hits = idx.search(body.q, vec, body.k)
    return {"ms": int((time.monotonic() - t0) * 1000), "hits": [{**h.__dict__} for h in hits]}


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=8000)


class ChatIn(BaseModel):
    q: str = Field(min_length=1, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    k: int | None = Field(default=None, ge=1, le=20)


@router.post("/chat/test")
def chat_test(body: ChatIn, c: Container = Depends(container), _: User = Depends(reviewer)):
    """Chat thử với tài liệu đã index. Không lưu câu hỏi và không ghi nội dung vào log."""
    from app.services import chat
    from app.services.config_service import NotConfigured

    try:
        return chat.ask(c, body.q, [t.model_dump() for t in body.history], body.k)
    except NotConfigured as e:
        raise HTTPException(409, {"code": f"{e.component}_not_configured"}) from e


@router.get("/search/status")
def search_status(c: Container = Depends(container), _: User = Depends(viewer)):
    from app.services.config_service import NotConfigured

    try:
        return {"configured": True, "count": c.config.adapter("search").count()}
    except NotConfigured:
        return {"configured": False, "count": 0}
    except Exception as e:  # noqa: BLE001
        return {"configured": True, "count": 0, "error": str(e)[:200]}
