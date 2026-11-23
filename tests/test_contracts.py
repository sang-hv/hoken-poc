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
AZURITE = os.environ.get("TEST_AZURITE_CONNECTION_STRING", "")

try:
    import moto  # noqa: F401

    HAS_MOTO = True
except ImportError:
    HAS_MOTO = False

aws_only = pytest.mark.skipif(not HAS_MOTO, reason="moto")
azurite_only = pytest.mark.skipif(not AZURITE, reason="TEST_AZURITE_CONNECTION_STRING")


@pytest.fixture(autouse=True)
def _aws_mock(request, monkeypatch):
    """Bật moto cho các tham số aws-*."""
    if "aws" not in request.node.callspec.id if hasattr(request.node, "callspec") else True:
        yield
        return
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    from moto import mock_aws

    with mock_aws():
        yield


def _stores():
    yield pytest.param(lambda: MemoryStore(), id="memory")
    yield pytest.param(_pg_store, id="postgres", marks=pytest.mark.skipif(not PG, reason="TEST_DATABASE_URL"))
    yield pytest.param(_ddb_store, id="aws-dynamodb", marks=aws_only)


def _ddb_store():
    from app.adapters.aws.dynamodb import DynamoStore

    return DynamoStore("hoken-test", "ap-northeast-1")


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
    yield pytest.param(_sqs_queue, id="aws-sqs", marks=aws_only)
    yield pytest.param(_azure_queue, id="azure-queue", marks=azurite_only)


def _sqs_queue():
    import boto3

    from app.adapters.aws.sqs import SqsQueue

    sqs = boto3.client("sqs", region_name="ap-northeast-1")
    url = sqs.create_queue(QueueName="hoken-light")["QueueUrl"]
    return SqsQueue(url[: -len("light")], "ap-northeast-1")


def _azure_queue():
    from app.adapters.azure.storage_queue import AzureStorageQueue

    return AzureStorageQueue("", AZURITE, f"t{uuid.uuid4().hex[:8]}")


def _pg_queue():
    from app.adapters.local.pg_queue import PgQueue

    return PgQueue(PG, f"t{uuid.uuid4().hex[:6]}")


@pytest.mark.parametrize("factory", list(_queues()))
def test_queue_contract(factory):
    q = factory()
    q.send("light", {"job_id": "1"})
    q.send("light", {"job_id": "2"})
    q.send("light", {"job_id": "3"}, delay_s=60)
    got = sorted(q.receive("light", 5, visibility_s=60), key=lambda m: m.body["job_id"])
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


# ------------------------------------------------------------------ blob
def _blobs(tmp_path_factory=None):
    from app.adapters.memory import MemoryBlob

    yield pytest.param(lambda tmp: MemoryBlob(), id="memory")
    yield pytest.param(_fs_blob, id="local-fs")
    yield pytest.param(_s3_blob, id="aws-s3", marks=aws_only)
    yield pytest.param(_azure_blob, id="azure-blob", marks=azurite_only)


def _fs_blob(tmp):
    from app.adapters.local.fs_blob import FsBlob

    return FsBlob(str(tmp))


def _s3_blob(tmp):
    import boto3

    from app.adapters.aws.s3 import S3Blob

    boto3.client("s3", region_name="ap-northeast-1").create_bucket(
        Bucket="hoken-test", CreateBucketConfiguration={"LocationConstraint": "ap-northeast-1"}
    )
    return S3Blob("hoken-test", "ap-northeast-1")


def _azure_blob(tmp):
    from app.adapters.azure.blob import AzureBlob

    return AzureBlob("", f"t{uuid.uuid4().hex[:8]}", AZURITE)


@pytest.mark.parametrize("factory", list(_blobs()))
def test_blob_contract(factory, tmp_path):
    b = factory(tmp_path)
    b.put("docs/d1/source.pdf", b"%PDF-1", "application/pdf")
    b.put("docs/d1/pages/0001/image.png", b"png")
    b.put("docs/d2/source.pdf", b"x")
    assert b.get("docs/d1/source.pdf") == b"%PDF-1"
    assert b.exists("docs/d1/pages/0001/image.png") and not b.exists("docs/d1/nope")
    with pytest.raises(FileNotFoundError):
        b.get("docs/d1/nope")
    b.delete_prefix("docs/d1")
    assert not b.exists("docs/d1/source.pdf") and b.exists("docs/d2/source.pdf")
