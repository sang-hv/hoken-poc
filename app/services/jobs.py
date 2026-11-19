"""Job: tạo (idempotent theo khoá docId:step:page), chạy, retry, huỷ, ghi live log."""

from __future__ import annotations

import logging
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.util import now_iso
from app.domain.models import Document, Job, JobEvent, JobStatus, page_key
from app.domain.options import PipelineOptions
from app.ports import QueueMessage
from app.services.container import Container

log = logging.getLogger("hoken.jobs")

QUEUES = ("docling", "ai", "light")


class JobCancelled(Exception):
    pass


class StepSkipped(Exception):
    """Step không chạy được vì thiếu điều kiện (vd. chưa cấu hình dịch vụ) — không retry."""


@dataclass
class Next:
    step: str
    page: int | None = None
    params: dict[str, Any] = field(default_factory=dict)
    force: bool = True


@dataclass
class StepCtx:
    c: Container
    job: Job
    doc: Document
    options: PipelineOptions

    def emit(self, code: str, level: str = "info", **params: Any) -> None:
        self.c.repo.add_event(
            JobEvent(
                id="",
                doc_id=self.job.doc_id,
                job_id=self.job.id,
                step=self.job.step,
                page=self.job.page,
                level=level,
                code=code,
                params=params,
            )
        )

    def check_cancelled(self) -> None:
        j = self.c.repo.get_job(self.job.id)
        if j and j.status == JobStatus.cancelled:
            raise JobCancelled()

    def adapter(self, component: str):
        return self.c.config.adapter(component)


@dataclass(frozen=True)
class StepDef:
    queue: str
    handler: Callable[[StepCtx], list[Next]]
    max_attempts: int = 3


STEPS: dict[str, StepDef] = {}


def register(step: str, queue: str, max_attempts: int = 3):
    def deco(fn):
        STEPS[step] = StepDef(queue, fn, max_attempts)
        return fn

    return deco


def job_id(doc_id: str, step: str, page: int | None) -> str:
    return f"{doc_id}:{step}:{page_key(page) if page else '-'}"


def emit(c: Container, doc_id: str, code: str, level: str = "info", job: Job | None = None, **params: Any):
    c.repo.add_event(
        JobEvent(
            id="",
            doc_id=doc_id,
            job_id=job.id if job else "",
            step=job.step if job else "",
            page=job.page if job else None,
            level=level,
            code=code,
            params=params,
        )
    )


def enqueue(
    c: Container,
    doc_id: str,
    step: str,
    page: int | None = None,
    params: dict | None = None,
    force: bool = True,
    actor: str = "system",
) -> Job | None:
    """Tạo job (hoặc đặt lại job cũ đã xong/lỗi) rồi gửi vào hàng đợi.

    Job đang queued/running thì bỏ qua — chống chạy trùng khi nhiều worker cùng kích hoạt (fan-in).
    """
    sd = STEPS[step]
    version, _ = c.config.pipeline()
    job = Job(
        id=job_id(doc_id, step, page),
        doc_id=doc_id,
        step=step,
        queue=sd.queue,
        page=page,
        params=params or {},
        max_attempts=sd.max_attempts,
        config_version=version,
        created_by=actor,
    )
    if not c.repo.create_job(job):
        existing = c.repo.get_job(job.id)
        if existing is None:
            return None
        if existing.status in (JobStatus.queued, JobStatus.running) or not force:
            return None
        existing.status, existing.attempts, existing.error = JobStatus.queued, 0, ""
        existing.params, existing.config_version, existing.created_by = job.params, version, actor
        existing.started_at = existing.finished_at = ""
        c.repo.save_job(existing)
        job = existing
    c.queue.send(sd.queue, {"job_id": job.id})
    emit(c, doc_id, "job.queued", job=job)
    return job


def cancel(c: Container, jid: str, actor: str) -> Job | None:
    j = c.repo.get_job(jid)
    if not j or j.status in (JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled):
        return j
    j.status = JobStatus.cancelled
    j.finished_at = now_iso()
    c.repo.save_job(j)
    emit(c, j.doc_id, "job.cancelled", "warn", job=j, by=actor)
    return j


def retry(c: Container, jid: str, actor: str) -> Job | None:
    j = c.repo.get_job(jid)
    if not j:
        return None
    return enqueue(c, j.doc_id, j.step, j.page, j.params, force=True, actor=actor)


def process_message(c: Container, queue: str, msg: QueueMessage) -> None:
    jid = msg.body.get("job_id", "")
    job = c.repo.get_job(jid)
    if job is None or job.status in (JobStatus.cancelled, JobStatus.succeeded, JobStatus.failed):
        c.queue.ack(queue, msg)
        return
    doc = c.repo.get_doc(job.doc_id)
    if doc is None:
        c.queue.ack(queue, msg)
        return
    sd = STEPS[job.step]
    job.status, job.attempts, job.started_at, job.error = JobStatus.running, job.attempts + 1, now_iso(), ""
    c.repo.save_job(job)
    ctx = StepCtx(c, job, doc, c.config.pipeline_at(job.config_version))
    ctx.emit("job.started", attempt=job.attempts)
    t0 = time.monotonic()
    try:
        nexts = sd.handler(ctx)
    except JobCancelled:
        c.queue.ack(queue, msg)
        return
    except StepSkipped as e:
        job.status, job.error, job.finished_at = JobStatus.failed, str(e)[:500], now_iso()
        c.repo.save_job(job)
        ctx.emit("job.blocked", "error", reason=str(e)[:300])
        c.queue.ack(queue, msg)
        return
    except Exception as e:  # noqa: BLE001
        log.warning("job %s failed: %s", job.id, traceback.format_exc(limit=3))
        err = f"{type(e).__name__}: {str(e)[:400]}"
        fresh = c.repo.get_job(job.id) or job
        if fresh.status == JobStatus.cancelled:
            c.queue.ack(queue, msg)
            return
        if job.attempts < job.max_attempts:
            job.status, job.error = JobStatus.queued, err
            c.repo.save_job(job)
            delay = 15 * 2 ** (job.attempts - 1)
            ctx.emit("job.retry", "warn", attempt=job.attempts, delay_s=delay, error=err)
            c.queue.release(queue, msg, delay)
        else:
            job.status, job.error, job.finished_at = JobStatus.failed, err, now_iso()
            c.repo.save_job(job)
            ctx.emit("job.failed", "error", error=err)
            from app.services.pipeline import on_job_failed

            on_job_failed(c, job)
            c.queue.ack(queue, msg)
        return
    fresh = c.repo.get_job(job.id) or job
    if fresh.status == JobStatus.cancelled:
        c.queue.ack(queue, msg)
        return
    job.status, job.finished_at = JobStatus.succeeded, now_iso()
    c.repo.save_job(job)
    ctx.emit("job.succeeded", ms=int((time.monotonic() - t0) * 1000))
    for n in nexts:
        enqueue(c, job.doc_id, n.step, n.page, n.params, force=n.force, actor="system")
    c.queue.ack(queue, msg)


def run_worker(
    c: Container,
    queues: list[str],
    *,
    drain: bool = False,
    idle_exit_s: float = 0,
    poll_s: float = 1.0,
    stop: Callable[[], bool] | None = None,
) -> int:
    """Chạy liên tục (worker trên VM/compose) hoặc chạy đến khi hết việc (drain — Container Apps Job / ECS task)."""
    processed = 0
    idle_since = time.monotonic()
    while not (stop and stop()):
        got = False
        for q in queues:
            for msg in c.queue.receive(q, 1, visibility_s=1800):
                got = True
                process_message(c, q, msg)
                processed += 1
        if got:
            idle_since = time.monotonic()
            continue
        if drain and time.monotonic() - idle_since >= idle_exit_s:
            break
        time.sleep(poll_s)
    return processed
