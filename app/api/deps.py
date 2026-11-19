"""Phụ thuộc chung của API: container, phiên đăng nhập (cookie JWT), phân quyền theo vai trò."""

from __future__ import annotations

import time

import jwt
from fastapi import Depends, HTTPException, Request, Response

from app.domain.models import ROLE_RANK, Role, User
from app.services.container import Container, get_container

COOKIE = "hoken_session"


def container() -> Container:
    return get_container()


def issue_session(resp: Response, c: Container, user: User) -> None:
    s = c.settings
    exp = int(time.time()) + s.session_hours * 3600
    token = jwt.encode({"sub": user.id, "role": user.role.value, "exp": exp}, s.jwt_secret, algorithm="HS256")
    resp.set_cookie(
        COOKIE, token, httponly=True, samesite="lax", secure=s.is_prod, max_age=s.session_hours * 3600, path="/"
    )


def clear_session(resp: Response) -> None:
    resp.delete_cookie(COOKIE, path="/")


def current_user(request: Request, c: Container = Depends(container)) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, {"code": "unauthenticated"})
    try:
        claims = jwt.decode(token, c.settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(401, {"code": "session_expired"}) from e
    user = c.repo.get_user(claims["sub"])
    if not user or not user.active:
        raise HTTPException(401, {"code": "unauthenticated"})
    return user


def require(role: Role):
    def dep(user: User = Depends(current_user)) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[role]:
            raise HTTPException(403, {"code": "forbidden", "need": role.value})
        return user

    return dep


viewer = require(Role.viewer)
reviewer = require(Role.reviewer)
admin = require(Role.admin)
