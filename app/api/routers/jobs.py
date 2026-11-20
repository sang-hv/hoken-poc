"""Job, live log (SSE), dashboard."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.api.deps import container, reviewer, viewer
from app.domain.models import DocStatus, JobStatus, User
from app.services import jobs as job_svc
from app.services.container import Container

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs")
def list_jobs(
    status: str = "",
    step: str = "",
    doc_id: str = "",
    q: str = "",
    limit: int = Query(300, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    paged: bool = False,
    c: Container = Depends(container),
    _: User = Depends(viewer),
):
    """`q` lọc theo tên tài liệu. `paged=true` trả {items, total} để UI phân trang; mặc định trả mảng như cũ."""
    eq = {k: v for k, v in {"status": status, "step": step, "doc_id": doc_id}.items() if v}
    names = {d.id: d.name for d in c.repo.list_docs()}
    jobs = c.repo.list_jobs(eq)
    if q.strip():
        needle = q.strip().lower()
        jobs = [j for j in jobs if needle in names.get(j.doc_id, "").lower()]
    items = [{**j.model_dump(mode="json"), "doc_name": names.get(j.doc_id, "")} for j in jobs[offset : offset + limit]]
    return {"items": items, "total": len(jobs)} if paged else items


@router.get("/jobs/{job_id}")
def get_job(job_id: str, c: Container = Depends(container), _: User = Depends(viewer)):
    j = c.repo.get_job(job_id)
    if not j:
        raise HTTPException(404, {"code": "job_not_found"})
    events = c.repo.recent_events(j.doc_id, 500, job_id=j.id)
    doc = c.repo.get_doc(j.doc_id)
    return {
        **j.model_dump(mode="json"),
        "doc_name": doc.name if doc else "",
        "events": [e.model_dump(mode="json") for e in events],
    }


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, c: Container = Depends(container), user: User = Depends(reviewer)):
    j = job_svc.retry(c, job_id, user.email)
    return {"job": j.model_dump(mode="json") if j else None}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, c: Container = Depends(container), user: User = Depends(reviewer)):
    j = job_svc.cancel(c, job_id, user.email)
    return {"job": j.model_dump(mode="json") if j else None}


@router.get("/documents/{doc_id}/events")
def doc_events(
    doc_id: str, after: str = "", limit: int = 300, c: Container = Depends(container), _: User = Depends(viewer)
):
    evs = c.repo.events(doc_id, after or None, limit=limit) if after else c.repo.recent_events(doc_id, limit)
    return [e.model_dump(mode="json") for e in evs]


async def _sse(request: Request, c: Container, doc_id: str, job_id: str | None, after: str):
    cursor = after or None
    if cursor is None:
        recent = await run_in_threadpool(c.repo.recent_events, doc_id, 200, job_id)
        for e in recent:
            yield f"id: {e.id}\nevent: log\ndata: {json.dumps(e.model_dump(mode='json'), ensure_ascii=False)}\n\n"
            cursor = e.id
        cursor = cursor or "0"
    idle = 0
    while not await request.is_disconnected():
        evs = await run_in_threadpool(c.repo.events, doc_id, cursor, job_id, 200)
        for e in evs:
            yield f"id: {e.id}\nevent: log\ndata: {json.dumps(e.model_dump(mode='json'), ensure_ascii=False)}\n\n"
            cursor = e.id
        idle = 0 if evs else idle + 1
        if idle and idle % 15 == 0:
            yield ": keep-alive\n\n"
        await asyncio.sleep(1.0)


@router.get("/stream/documents/{doc_id}")
async def stream_doc(doc_id: str, request: Request, c: Container = Depends(container), _: User = Depends(viewer)):
    after = request.headers.get("last-event-id", "")
    return StreamingResponse(
        _sse(request, c, doc_id, None, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/stream/jobs/{job_id}")
async def stream_job(job_id: str, request: Request, c: Container = Depends(container), _: User = Depends(viewer)):
    j = c.repo.get_job(job_id)
    if not j:
        raise HTTPException(404, {"code": "job_not_found"})
    after = request.headers.get("last-event-id", "")
    return StreamingResponse(
        _sse(request, c, j.doc_id, j.id, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/dashboard")
def dashboard(c: Container = Depends(container), _: User = Depends(viewer)):
    docs = c.repo.list_docs()
    jobs = c.repo.list_jobs()
    by_status = {s.value: 0 for s in DocStatus}
    pages_review = chunks_review = 0
    for d in docs:
        by_status[d.status.value] += 1
        pages_review += d.stats.get("review", 0)
        if d.status == DocStatus.chunk_review:
            chunks_review += d.stats.get("chunks", 0) - d.stats.get("chunks_approved", 0)
    job_counts = {s.value: 0 for s in JobStatus}
    for j in jobs:
        job_counts[j.status.value] += 1
    queues = {}
    for q in job_svc.QUEUES:
        try:
            queues[q] = c.queue.depth(q)
        except Exception:  # noqa: BLE001
            queues[q] = -1
    return {
        "documents": len(docs),
        "documents_by_status": by_status,
        "pages_to_review": pages_review,
        "chunks_to_review": chunks_review,
        "jobs": job_counts,
        "queues": queues,
        "recent_failed": [j.model_dump(mode="json") for j in jobs if j.status == JobStatus.failed][:10],
        "configured": {k: c.config.is_configured(k) for k in ("llm", "embedding", "cu", "search")},
    }
