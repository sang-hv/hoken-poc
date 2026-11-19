"""DocStore trên PostgreSQL: một bảng JSONB, khoá (coll, pk, id)."""

from __future__ import annotations

import atexit
import json
from typing import Any

from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

DDL = """
CREATE TABLE IF NOT EXISTS docs (
    coll text NOT NULL,
    pk   text NOT NULL,
    id   text NOT NULL,
    data jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (coll, pk, id)
);
CREATE INDEX IF NOT EXISTS docs_data_gin ON docs USING gin (data jsonb_path_ops);
"""

_pools: dict[str, ConnectionPool] = {}


def get_pool(dsn: str) -> ConnectionPool:
    if dsn not in _pools:
        _pools[dsn] = ConnectionPool(dsn, min_size=1, max_size=10, kwargs={"autocommit": True}, open=True)
        atexit.register(_pools[dsn].close)
    return _pools[dsn]


class PgStore:
    def __init__(self, dsn: str):
        self.pool = get_pool(dsn)
        with self.pool.connection() as c:
            c.execute(DDL)

    def get(self, coll: str, pk: str, id: str) -> dict | None:
        with self.pool.connection() as c:
            row = c.execute("SELECT data FROM docs WHERE coll=%s AND pk=%s AND id=%s", (coll, pk, id)).fetchone()
        return row[0] if row else None

    def put(self, coll: str, pk: str, id: str, doc: dict) -> None:
        with self.pool.connection() as c:
            c.execute(
                "INSERT INTO docs (coll, pk, id, data) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (coll, pk, id) DO UPDATE SET data=EXCLUDED.data, updated_at=now()",
                (coll, pk, id, Jsonb(doc)),
            )

    def create(self, coll: str, pk: str, id: str, doc: dict) -> bool:
        with self.pool.connection() as c:
            cur = c.execute(
                "INSERT INTO docs (coll, pk, id, data) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (coll, pk, id, Jsonb(doc)),
            )
            return cur.rowcount == 1

    def delete(self, coll: str, pk: str, id: str) -> None:
        with self.pool.connection() as c:
            c.execute("DELETE FROM docs WHERE coll=%s AND pk=%s AND id=%s", (coll, pk, id))

    def delete_partition(self, coll: str, pk: str) -> None:
        with self.pool.connection() as c:
            c.execute("DELETE FROM docs WHERE coll=%s AND pk=%s", (coll, pk))

    def query(
        self,
        coll: str,
        pk: str,
        eq: dict[str, Any] | None = None,
        id_gt: str | None = None,
        limit: int = 1000,
        desc: bool = False,
    ) -> list[dict]:
        sql = "SELECT data FROM docs WHERE coll=%s AND pk=%s"
        args: list[Any] = [coll, pk]
        if eq:
            sql += " AND data @> %s::jsonb"
            args.append(json.dumps(eq))
        if id_gt:
            sql += " AND id > %s"
            args.append(id_gt)
        sql += f" ORDER BY id {'DESC' if desc else 'ASC'} LIMIT %s"
        args.append(limit)
        with self.pool.connection() as c:
            c.row_factory = tuple_row
            return [r[0] for r in c.execute(sql, args).fetchall()]

    def health(self) -> None:
        with self.pool.connection() as c:
            c.execute("SELECT 1")
