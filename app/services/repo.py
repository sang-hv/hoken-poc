"""Repository có kiểu trên DocStore. Mọi đọc/ghi dữ liệu nghiệp vụ đi qua đây."""

from __future__ import annotations

from typing import Any

from app.core.util import new_id, now_iso
from app.domain.models import (
    GLOBAL,
    AuditEntry,
    Chunk,
    Document,
    Job,
    JobEvent,
    Page,
    User,
    page_key,
)
from app.ports import DocStore


class Repo:
    def __init__(self, store: DocStore):
        self.s = store

    # ---------------------------------------------------------------- documents
    def get_doc(self, doc_id: str) -> Document | None:
        d = self.s.get("documents", GLOBAL, doc_id)
        return Document(**d) if d else None

    def save_doc(self, doc: Document) -> Document:
        doc.updated_at = now_iso()
        self.s.put("documents", GLOBAL, doc.id, doc.model_dump(mode="json"))
        return doc

    def list_docs(self) -> list[Document]:
        return [Document(**d) for d in self.s.query("documents", GLOBAL, desc=True)]

    def delete_doc(self, doc_id: str) -> None:
        for coll in ("pages", "chunks", "events"):
            self.s.delete_partition(coll, doc_id)
        for j in self.s.query("jobs", GLOBAL, eq={"doc_id": doc_id}):
            self.s.delete("jobs", GLOBAL, j["id"])
        self.s.delete("documents", GLOBAL, doc_id)

    # ---------------------------------------------------------------- pages
    def get_page(self, doc_id: str, page: int) -> Page | None:
        d = self.s.get("pages", doc_id, page_key(page))
        return Page(**d) if d else None

    def save_page(self, p: Page) -> Page:
        p.updated_at = now_iso()
        self.s.put("pages", p.doc_id, p.id, p.model_dump(mode="json"))
        return p

    def list_pages(self, doc_id: str) -> list[Page]:
        return [Page(**d) for d in self.s.query("pages", doc_id, limit=5000)]

    # ---------------------------------------------------------------- chunks
    def list_chunks(self, doc_id: str) -> list[Chunk]:
        return sorted((Chunk(**d) for d in self.s.query("chunks", doc_id, limit=20000)), key=lambda c: c.seq)

    def get_chunk(self, doc_id: str, chunk_id: str) -> Chunk | None:
        d = self.s.get("chunks", doc_id, chunk_id)
        return Chunk(**d) if d else None

    def save_chunk(self, c: Chunk) -> Chunk:
        c.updated_at = now_iso()
        self.s.put("chunks", c.doc_id, c.id, c.model_dump(mode="json"))
        return c

    def delete_chunk(self, doc_id: str, chunk_id: str) -> None:
        self.s.delete("chunks", doc_id, chunk_id)

    def replace_chunks(self, doc_id: str, chunks: list[Chunk]) -> None:
        self.s.delete_partition("chunks", doc_id)
        for c in chunks:
            self.save_chunk(c)

    # ---------------------------------------------------------------- jobs
    def get_job(self, job_id: str) -> Job | None:
        d = self.s.get("jobs", GLOBAL, job_id)
        return Job(**d) if d else None

    def save_job(self, job: Job) -> Job:
        job.updated_at = now_iso()
        self.s.put("jobs", GLOBAL, job.id, job.model_dump(mode="json"))
        return job

    def create_job(self, job: Job) -> bool:
        job.created_at = job.updated_at = now_iso()
        return self.s.create("jobs", GLOBAL, job.id, job.model_dump(mode="json"))

    def list_jobs(self, eq: dict[str, Any] | None = None, limit: int = 2000) -> list[Job]:
        jobs = [Job(**d) for d in self.s.query("jobs", GLOBAL, eq=eq or None, limit=limit)]
        return sorted(jobs, key=lambda j: j.updated_at, reverse=True)

    # ---------------------------------------------------------------- live log
    def add_event(self, ev: JobEvent) -> JobEvent:
        ev.id = ev.id or new_id()
        ev.ts = ev.ts or now_iso()
        self.s.put("events", ev.doc_id, ev.id, ev.model_dump(mode="json"))
        return ev

    def events(
        self, doc_id: str, after: str | None = None, job_id: str | None = None, limit: int = 500
    ) -> list[JobEvent]:
        eq = {"job_id": job_id} if job_id else None
        return [JobEvent(**d) for d in self.s.query("events", doc_id, eq=eq, id_gt=after, limit=limit)]

    def recent_events(self, doc_id: str, limit: int = 300, job_id: str | None = None) -> list[JobEvent]:
        eq = {"job_id": job_id} if job_id else None
        evs = self.s.query("events", doc_id, eq=eq, limit=limit, desc=True)
        return [JobEvent(**d) for d in reversed(evs)]

    # ---------------------------------------------------------------- users
    def get_user(self, user_id: str) -> User | None:
        d = self.s.get("users", GLOBAL, user_id)
        return User(**d) if d else None

    def find_user_by_email(self, email: str) -> User | None:
        found = self.s.query("users", GLOBAL, eq={"email": email.lower()}, limit=1)
        return User(**found[0]) if found else None

    def save_user(self, u: User) -> User:
        u.email = u.email.lower()
        self.s.put("users", GLOBAL, u.id, u.model_dump(mode="json"))
        return u

    def list_users(self) -> list[User]:
        return [User(**d) for d in self.s.query("users", GLOBAL)]

    def delete_user(self, user_id: str) -> None:
        self.s.delete("users", GLOBAL, user_id)

    # ---------------------------------------------------------------- audit
    def audit(self, actor: str, action: str, target: str = "", **detail: Any) -> None:
        e = AuditEntry(id=new_id(), actor=actor, action=action, target=target, detail=detail, at=now_iso())
        self.s.put("audit", GLOBAL, e.id, e.model_dump(mode="json"))

    def list_audit(self, limit: int = 300) -> list[AuditEntry]:
        return [AuditEntry(**d) for d in self.s.query("audit", GLOBAL, limit=limit, desc=True)]

    # ---------------------------------------------------------------- settings (lớp 2, 4)
    def get_setting(self, key: str) -> dict | None:
        return self.s.get("settings", GLOBAL, key)

    def put_setting(self, key: str, value: dict) -> None:
        self.s.put("settings", GLOBAL, key, value)

    def list_setting_history(self, key: str, limit: int = 50) -> list[dict]:
        return self.s.query("settings_history", key, limit=limit, desc=True)

    def add_setting_history(self, key: str, value: dict) -> None:
        self.s.put("settings_history", key, new_id(), value)
