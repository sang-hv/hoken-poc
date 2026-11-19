"""Test hợp đồng: cùng một bộ test cho mọi adapter của một port.

Adapter cloud chạy khi có biến môi trường tương ứng (vd TEST_DATABASE_URL cho Postgres,
TEST_COSMOS_ENDPOINT, TEST_DYNAMODB_TABLE...). Không có thì bỏ qua.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.adapters.memory import HashEmbedder, MemoryQueue, MemorySearch, MemoryStore
from app.ports import IndexDoc

PG = os.environ.get("TEST_DATABASE_URL", "")


def _stores():
    yield pytest.param(lambda: MemoryStore(), id="memory")
    yield pytest.param(_pg_store, id="postgres", marks=pytest.mark.skipif(not PG, reason="TEST_DATABASE_URL"))


def _pg_store():
    from app.adapters.local.pg_store import PgStore

    return PgStore(PG)


@pytest.mark.parametrize("factory", list(_stores()))
def test_docstore_contract(factory):
    s = factory()
    coll, pk = f"t{uuid.uuid4().hex[:8]}", "p1"
    assert s.get(coll, pk, "a") is None
    s.put(coll, pk, "a", {"id": "a", "k": 1, "tag": "x"})
    s.put(coll, pk, "b", {"id": "b", "k": 2, "tag": "y"})
    s.put(coll, pk, "c", {"id": "c", "k": 3, "tag": "x"})
    s.put(coll, "p2", "z", {"id": "z"})
    assert s.get(coll, pk, "a")["k"] == 1
    assert [d["id"] for d in s.query(coll, pk)] == ["a", "b", "c"]
    assert [d["id"] for d in s.query(coll, pk, desc=True, limit=2)] == ["c", "b"]
    assert [d["id"] for d in s.query(coll, pk, eq={"tag": "x"})] == ["a", "c"]
    assert [d["id"] for d in s.query(coll, pk, id_gt="a")] == ["b", "c"]
    assert s.create(coll, pk, "a", {"id": "a"}) is False
    assert s.create(coll, pk, "d", {"id": "d"}) is True
    s.delete(coll, pk, "d")
    assert s.get(coll, pk, "d") is None
    s.delete_partition(coll, pk)
    assert s.query(coll, pk) == [] and s.get(coll, "p2", "z")


def _queues():
    yield pytest.param(lambda: MemoryQueue(), id="memory")
    yield pytest.param(_pg_queue, id="postgres", marks=pytest.mark.skipif(not PG, reason="TEST_DATABASE_URL"))


def _pg_queue():
    from app.adapters.local.pg_queue import PgQueue

    return PgQueue(PG, f"t{uuid.uuid4().hex[:6]}")


@pytest.mark.parametrize("factory", list(_queues()))
def test_queue_contract(factory):
    q = factory()
    q.send("light", {"job_id": "1"})
    q.send("light", {"job_id": "2"})
    q.send("light", {"job_id": "3"}, delay_s=60)
    got = q.receive("light", 5, visibility_s=60)
    assert [m.body["job_id"] for m in got] == ["1", "2"]
    assert q.receive("light", 5, visibility_s=60) == []  # đang ẩn
    q.ack("light", got[0])
    q.release("light", got[1], 0)
    again = q.receive("light", 5, visibility_s=60)
    assert [m.body["job_id"] for m in again] == ["2"] and again[0].dequeue_count == 2
    q.ack("light", again[0])
    assert q.depth("light") == 1


def _searches():
    yield pytest.param(lambda: MemorySearch(), id="memory")
    yield pytest.param(_pg_search, id="postgres", marks=pytest.mark.skipif(not PG, reason="TEST_DATABASE_URL"))


def _pg_search():
    from app.adapters.local.pg_search import PgSearch

    return PgSearch(PG, f"t_{uuid.uuid4().hex[:8]}")


@pytest.mark.parametrize("factory", list(_searches()))
def test_search_contract(factory):
    s = factory()
    emb = HashEmbedder(64)
    s.ensure(64)
    texts = {
        "M015-2": "CAD/CAM冠用材料(Ⅲ)を使用した場合、1歯につき所定点数を算定する。",
        "M016": "金属歯冠修復は1歯につき算定する。ただし、前歯部は除く。",
        "A000": "初診料は264点とする。",
    }
    docs = [
        IndexDoc(
            id=f"d1-{k}",
            doc_id="d1",
            doc_name="赤本",
            item_code=k,
            title="",
            page_from=1,
            page_to=1,
            content=v,
            vector=emb.embed([v])[0],
        )
        for k, v in texts.items()
    ]
    s.upsert(docs)
    s.upsert(docs[:1])  # upsert lặp lại không tạo bản trùng
    assert s.count() == 3
    q = "CAD/CAM冠用材料の算定要件は？"
    hits = s.search(q, emb.embed([q])[0], 3)
    assert hits[0].item_code == "M015-2"
    s.set_enabled("d1", False)
    assert s.search(q, emb.embed([q])[0], 3) == []
    s.set_enabled("d1", True)
    s.delete_doc("d1")
    assert s.count() == 0
