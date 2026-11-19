"""Đăng nhập: tài khoản nội bộ + SSO OIDC (Google, Microsoft Entra ID). Màn Setup lần đầu tạo Admin."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from collections import defaultdict
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import clear_session, container, current_user, issue_session
from app.core.util import hash_password, new_id, now_iso, verify_password
from app.domain.models import Role, User
from app.services.container import Container

router = APIRouter(prefix="/api", tags=["auth"])

_failed: dict[str, list[float]] = defaultdict(list)


class SetupIn(BaseModel):
    email: EmailStr
    name: str = ""
    password: str = Field(min_length=10)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


@router.get("/setup/status")
def setup_status(c: Container = Depends(container)):
    return {"needs_setup": not c.repo.list_users(), "app_env": c.settings.app_env}


@router.post("/setup")
def setup(body: SetupIn, resp: Response, c: Container = Depends(container)):
    if c.repo.list_users():
        raise HTTPException(409, {"code": "already_setup"})
    u = User(
        id=new_id(),
        email=body.email,
        name=body.name,
        role=Role.admin,
        password_hash=hash_password(body.password),
        created_at=now_iso(),
    )
    c.repo.save_user(u)
    c.repo.audit(u.email, "setup.admin_created", u.id)
    issue_session(resp, c, u)
    return u.public()


@router.post("/auth/login")
def login(body: LoginIn, resp: Response, c: Container = Depends(container)):
    key = body.email.lower()
    now = time.time()
    _failed[key] = [t for t in _failed[key] if now - t < 300]
    if len(_failed[key]) >= 5:
        raise HTTPException(429, {"code": "too_many_attempts"})
    u = c.repo.find_user_by_email(key)
    if not u or not u.active or not u.password_hash or not verify_password(body.password, u.password_hash):
        _failed[key].append(now)
        raise HTTPException(401, {"code": "bad_credentials"})
    _failed.pop(key, None)
    u.last_login_at = now_iso()
    c.repo.save_user(u)
    issue_session(resp, c, u)
    return u.public()


@router.post("/auth/logout")
def logout(resp: Response):
    clear_session(resp)
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return user.public()


@router.get("/auth/providers")
def providers(c: Container = Depends(container)):
    a = c.config.auth()
    return {"providers": [name for name, v in a.items() if v["enabled"]]}


# ------------------------------------------------------------------ OIDC
def _discovery_url(name: str, cfg: dict) -> str:
    if name == "google":
        return "https://accounts.google.com/.well-known/openid-configuration"
    tenant = cfg.get("tenant_id") or "common"
    return f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration"


def _oidc_cfg(c: Container, name: str) -> dict:
    cfg = c.config.auth().get(name)
    if not cfg or not cfg["enabled"]:
        raise HTTPException(404, {"code": "provider_disabled"})
    return cfg


def _redirect_uri(c: Container, name: str) -> str:
    return f"{c.settings.public_base_url}/api/auth/oidc/{name}/callback"


@router.get("/auth/oidc/{name}/start")
def oidc_start(name: str, c: Container = Depends(container)):
    cfg = _oidc_cfg(c, name)
    meta = httpx.get(_discovery_url(name, cfg), timeout=10).json()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "client_id": cfg["client_id"],
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": _redirect_uri(c, name),
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    resp = RedirectResponse(meta["authorization_endpoint"] + "?" + urlencode(params))
    flow = jwt.encode(
        {"state": state, "nonce": nonce, "verifier": verifier, "exp": int(time.time()) + 600},
        c.settings.jwt_secret,
        algorithm="HS256",
    )
    resp.set_cookie(
        "hoken_oidc", flow, httponly=True, samesite="lax", secure=c.settings.is_prod, max_age=600, path="/api/auth/oidc"
    )
    return resp


@router.get("/auth/oidc/{name}/callback")
def oidc_callback(name: str, request: Request, code: str = "", state: str = "", c: Container = Depends(container)):
    base = c.settings.public_base_url
    try:
        cfg = _oidc_cfg(c, name)
        flow = jwt.decode(request.cookies.get("hoken_oidc", ""), c.settings.jwt_secret, algorithms=["HS256"])
        if not code or state != flow["state"]:
            raise ValueError("state")
        meta = httpx.get(_discovery_url(name, cfg), timeout=10).json()
        tok = httpx.post(
            meta["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _redirect_uri(c, name),
                "client_id": cfg["client_id"],
                "client_secret": c.config.auth_secret(name) or "",
                "code_verifier": flow["verifier"],
            },
            timeout=15,
        ).json()
        id_token = tok["id_token"]
        key = jwt.PyJWKClient(meta["jwks_uri"]).get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=cfg["client_id"],
            options={"verify_iss": name == "google"},
            issuer=meta["issuer"] if name == "google" else None,
        )
        if claims.get("nonce") != flow["nonce"]:
            raise ValueError("nonce")
        email = (claims.get("email") or claims.get("preferred_username") or "").lower()
        if not email or (name == "google" and not claims.get("email_verified", False)):
            raise ValueError("email")
    except Exception:  # noqa: BLE001
        return RedirectResponse(f"{base}/login?error=sso_failed")
    user = c.repo.find_user_by_email(email)
    domains = [d.strip().lower() for d in str(cfg.get("allowed_domains", "")).split(",") if d.strip()]
    if user is None:
        if not domains or email.split("@")[-1] not in domains:
            return RedirectResponse(f"{base}/login?error=sso_not_allowed")
        user = User(
            id=new_id(),
            email=email,
            name=claims.get("name", ""),
            role=Role(cfg["default_role"]),
            provider=name,
            created_at=now_iso(),
        )
        c.repo.audit(email, "user.sso_created", user.id, provider=name)
    if not user.active:
        return RedirectResponse(f"{base}/login?error=sso_not_allowed")
    user.last_login_at = now_iso()
    c.repo.save_user(user)
    resp = RedirectResponse(f"{base}/")
    resp.delete_cookie("hoken_oidc", path="/api/auth/oidc")
    issue_session(resp, c, user)
    return resp
