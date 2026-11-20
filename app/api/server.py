"""FastAPI app cho khu A (Ingestion & Review API)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import app.steps.handlers  # noqa: F401 — đăng ký step (API cần biết queue của từng step)
from app.api.routers import admin, auth, documents, inspect, jobs
from app.services.config_service import NotConfigured
from app.services.container import get_container
from app.services.pipeline import PipelineError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app() -> FastAPI:
    api = FastAPI(title="保険AI Bot — Ingestion API", version="0.1.0")
    s = get_container().settings
    if s.cors_origins:
        api.add_middleware(
            CORSMiddleware,
            allow_origins=list(s.cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @api.middleware("http")
    async def csrf_guard(request: Request, call_next):
        # Cookie SameSite=Lax + bắt buộc header tự đặt cho mọi request ghi → chặn CSRF từ site khác.
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and request.url.path.startswith("/api/")
            and request.headers.get("x-requested-with") != "hoken"
        ):
            return JSONResponse({"detail": {"code": "csrf"}}, status_code=403)
        return await call_next(request)

    @api.exception_handler(PipelineError)
    async def _pipeline_error(_, exc: PipelineError):
        return JSONResponse({"detail": {"code": exc.code, **exc.params}}, status_code=409)

    @api.exception_handler(NotConfigured)
    async def _not_configured(_, exc: NotConfigured):
        return JSONResponse({"detail": {"code": f"{exc.component}_not_configured"}}, status_code=409)

    @api.exception_handler(ValueError)
    async def _value_error(_, exc: ValueError):
        return JSONResponse({"detail": {"code": "invalid", "message": str(exc)[:300]}}, status_code=400)

    @api.exception_handler(RequestValidationError)
    async def _validation(_, exc: RequestValidationError):
        errs = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse({"detail": {"code": "invalid", "errors": errs}}, status_code=422)

    @api.get("/api/health")
    def health():
        return {"ok": True}

    for r in (auth.router, documents.router, jobs.router, admin.router, inspect.router):
        api.include_router(r)

    @api.exception_handler(HTTPException)
    async def _http(_, exc: HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return api


app = create_app()
