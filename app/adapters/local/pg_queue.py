"""Hàng đợi trên PostgreSQL (FOR UPDATE SKIP LOCKED) cho chế độ local / một VM."""

from __future__ import annotations

from psycopg.types.json import Jsonb

from app.adapters.local.pg_store import get_pool
from app.ports import QueueMessage

DDL = """
CREATE TABLE IF NOT EXISTS queue_messages (
    id bigserial PRIMARY KEY,
    queue text NOT NULL,
    body jsonb NOT NULL,
    visible_at timestamptz NOT NULL DEFAULT now(),
    dequeue_count int NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS queue_messages_ready ON queue_messages (queue, visible_at, id);
"""


class PgQueue:
    def __init__(self, dsn: str, prefix: str = "hoken"):
        self.pool = get_pool(dsn)
        self.prefix = prefix
        with self.pool.connection() as c:
            c.execute(DDL)

    def _q(self, queue: str) -> str:
        return f"{self.prefix}-{queue}"

    def send(self, queue: str, body: dict, delay_s: int = 0) -> None:
        with self.pool.connection() as c:
            c.execute(
                "INSERT INTO queue_messages (queue, body, visible_at) "
                "VALUES (%s, %s, now() + make_interval(secs => %s))",
                (self._q(queue), Jsonb(body), delay_s),
            )

    def receive(self, queue: str, max_messages: int = 1, visibility_s: int = 900) -> list[QueueMessage]:
        with self.pool.connection() as c:
            rows = c.execute(
                """
                UPDATE queue_messages SET visible_at = now() + make_interval(secs => %s),
                       dequeue_count = dequeue_count + 1
                WHERE id IN (
                    SELECT id FROM queue_messages
                    WHERE queue = %s AND visible_at <= now()
                    ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED
                )
                RETURNING id, body, dequeue_count
                """,
                (visibility_s, self._q(queue), max_messages),
            ).fetchall()
        rows.sort(key=lambda r: r[0])
        return [QueueMessage(id=str(r[0]), body=r[1], receipt=r[0], dequeue_count=r[2]) for r in rows]

    def ack(self, queue: str, msg: QueueMessage) -> None:
        with self.pool.connection() as c:
            c.execute("DELETE FROM queue_messages WHERE id = %s", (msg.receipt,))

    def release(self, queue: str, msg: QueueMessage, delay_s: int = 0) -> None:
        with self.pool.connection() as c:
            c.execute(
                "UPDATE queue_messages SET visible_at = now() + make_interval(secs => %s) WHERE id = %s",
                (delay_s, msg.receipt),
            )

    def depth(self, queue: str) -> int:
        with self.pool.connection() as c:
            return c.execute("SELECT count(*) FROM queue_messages WHERE queue = %s", (self._q(queue),)).fetchone()[0]
