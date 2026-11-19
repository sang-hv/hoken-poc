"""Search hybrid trên PostgreSQL: pgvector (ngữ nghĩa) + pg_bigm (từ khoá tiếng Nhật), gộp bằng RRF."""

from __future__ import annotations

import re

from app.adapters.local.pg_store import get_pool
from app.core.text import keyword_terms, rrf
from app.ports import IndexDoc, SearchHit

_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


class PgSearch:
    def __init__(self, dsn: str, index: str):
        if not _NAME_RE.match(index):
            raise ValueError("Tên index chỉ gồm a-z, 0-9, _")
        self.pool = get_pool(dsn)
        self.table = index

    @classmethod
    def from_config(cls, cfg: dict, secrets: dict) -> PgSearch:
        from app.core.settings import get_settings

        dsn = secrets.get("dsn") or get_settings().database_url
        return cls(dsn, cfg.get("index") or "hoken_chunks")

    def ensure(self, dims: int) -> None:
        t = self.table
        with self.pool.connection() as c:
            c.execute("CREATE EXTENSION IF NOT EXISTS vector")
            c.execute("CREATE EXTENSION IF NOT EXISTS pg_bigm")
            row = c.execute(
                "SELECT atttypmod FROM pg_attribute WHERE attrelid = to_regclass(%s) AND attname='embedding'",
                (t,),
            ).fetchone()
            if row and row[0] != dims:
                raise RuntimeError(f"Index {t} đang có {row[0]} chiều, embedding mới {dims} chiều — cần index lại")
            c.execute(
                f"""CREATE TABLE IF NOT EXISTS {t} (
                    id text PRIMARY KEY, doc_id text NOT NULL, doc_name text, item_code text, title text,
                    page_from int, page_to int, content text NOT NULL, enabled boolean NOT NULL DEFAULT true,
                    embedding vector({dims}) NOT NULL)"""
            )
            c.execute(f"CREATE INDEX IF NOT EXISTS {t}_doc ON {t} (doc_id)")
            c.execute(f"CREATE INDEX IF NOT EXISTS {t}_bigm ON {t} USING gin (content gin_bigm_ops)")
            if dims <= 2000:
                c.execute(f"CREATE INDEX IF NOT EXISTS {t}_hnsw ON {t} USING hnsw (embedding vector_cosine_ops)")

    def upsert(self, docs: list[IndexDoc]) -> None:
        if not docs:
            return
        with self.pool.connection() as c:
            with c.cursor() as cur:
                cur.executemany(
                    f"""INSERT INTO {self.table}
                        (id, doc_id, doc_name, item_code, title, page_from, page_to, content, enabled, embedding)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                        ON CONFLICT (id) DO UPDATE SET doc_name=EXCLUDED.doc_name, item_code=EXCLUDED.item_code,
                        title=EXCLUDED.title, page_from=EXCLUDED.page_from, page_to=EXCLUDED.page_to,
                        content=EXCLUDED.content, enabled=EXCLUDED.enabled, embedding=EXCLUDED.embedding""",
                    [
                        (
                            d.id,
                            d.doc_id,
                            d.doc_name,
                            d.item_code,
                            d.title,
                            d.page_from,
                            d.page_to,
                            d.content,
                            d.enabled,
                            _vec(d.vector),
                        )
                        for d in docs
                    ],
                )

    def delete_doc(self, doc_id: str) -> None:
        with self.pool.connection() as c:
            if self._exists(c):
                c.execute(f"DELETE FROM {self.table} WHERE doc_id=%s", (doc_id,))

    def set_enabled(self, doc_id: str, enabled: bool) -> None:
        with self.pool.connection() as c:
            if self._exists(c):
                c.execute(f"UPDATE {self.table} SET enabled=%s WHERE doc_id=%s", (enabled, doc_id))

    def _exists(self, c) -> bool:
        return c.execute("SELECT to_regclass(%s)", (self.table,)).fetchone()[0] is not None

    def search(self, text: str, vector: list[float], k: int = 5) -> list[SearchHit]:
        n = max(k * 10, 50)
        cols = "id, doc_id, doc_name, item_code, title, page_from, page_to, content"
        rows: dict[str, tuple] = {}
        vec_rank: list[str] = []
        kw_rank: list[str] = []
        vec_score: dict[str, float] = {}
        kw_score: dict[str, float] = {}
        with self.pool.connection() as c:
            if not self._exists(c):
                return []
            for r in c.execute(
                f"SELECT {cols}, 1 - (embedding <=> %s::vector) FROM {self.table} WHERE enabled "
                f"ORDER BY embedding <=> %s::vector LIMIT %s",
                (_vec(vector), _vec(vector), n),
            ).fetchall():
                rows[r[0]] = r[:8]
                vec_rank.append(r[0])
                vec_score[r[0]] = float(r[8])
            terms = keyword_terms(text)
            if terms:
                score_sql = " + ".join(["(CASE WHEN content LIKE likequery(%s) THEN %s ELSE 0 END)"] * len(terms))
                where = " OR ".join(["content LIKE likequery(%s)"] * len(terms))
                args: list = []
                for t in terms:
                    args += [t, len(t)]
                args += terms + [n]
                for r in c.execute(
                    f"SELECT {cols}, ({score_sql}) AS s FROM {self.table} WHERE enabled AND ({where}) "
                    f"ORDER BY s DESC, id LIMIT %s",
                    args,
                ).fetchall():
                    rows[r[0]] = r[:8]
                    kw_rank.append(r[0])
                    kw_score[r[0]] = float(r[8])
        fused = rrf([vec_rank, kw_rank])
        hits = []
        for key, score in sorted(fused.items(), key=lambda kv: -kv[1])[:k]:
            r = rows[key]
            hits.append(
                SearchHit(
                    id=r[0],
                    doc_id=r[1],
                    doc_name=r[2] or "",
                    item_code=r[3] or "",
                    title=r[4] or "",
                    page_from=r[5] or 0,
                    page_to=r[6] or 0,
                    content=r[7],
                    score=score,
                    scores={"vector": vec_score.get(key, 0.0), "keyword": kw_score.get(key, 0.0)},
                )
            )
        return hits

    def count(self) -> int:
        with self.pool.connection() as c:
            if not self._exists(c):
                return 0
            return c.execute(f"SELECT count(*) FROM {self.table}").fetchone()[0]

    def health(self) -> None:
        with self.pool.connection() as c:
            c.execute("SELECT 1")
            for ext in ("vector", "pg_bigm"):
                ok = c.execute("SELECT 1 FROM pg_available_extensions WHERE name=%s", (ext,)).fetchone()
                if not ok:
                    raise RuntimeError(f"Postgres thiếu extension {ext}")
