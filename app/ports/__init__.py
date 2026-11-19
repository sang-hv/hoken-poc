"""Ports: interface mà mọi adapter (local / azure / aws / memory) phải thoả.

Step và service chỉ phụ thuộc vào các interface này, không import SDK của cloud nào.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


# ------------------------------------------------------------------ DB (document store)
@runtime_checkable
class DocStore(Protocol):
    """Kho document đơn giản, map được sang Postgres (JSONB), Cosmos DB và DynamoDB.

    - Mỗi document thuộc (collection, partition). Khoá là (collection, partition, id).
    - `query` luôn trong một partition, kết quả sắp theo `id` (id có thứ tự thời gian → dùng làm con trỏ).
    """

    def get(self, coll: str, pk: str, id: str) -> dict | None: ...
    def put(self, coll: str, pk: str, id: str, doc: dict) -> None: ...
    def create(self, coll: str, pk: str, id: str, doc: dict) -> bool:
        """Chỉ ghi khi chưa tồn tại. Trả về False nếu đã có (dùng để chống tạo trùng job)."""
        ...

    def delete(self, coll: str, pk: str, id: str) -> None: ...
    def delete_partition(self, coll: str, pk: str) -> None: ...
    def query(
        self,
        coll: str,
        pk: str,
        eq: dict[str, Any] | None = None,
        id_gt: str | None = None,
        limit: int = 1000,
        desc: bool = False,
    ) -> list[dict]: ...
    def health(self) -> None: ...


# ------------------------------------------------------------------ hàng đợi
@dataclass
class QueueMessage:
    id: str
    body: dict
    receipt: Any = None
    dequeue_count: int = 1


@runtime_checkable
class Queue(Protocol):
    def send(self, queue: str, body: dict, delay_s: int = 0) -> None: ...
    def receive(self, queue: str, max_messages: int = 1, visibility_s: int = 900) -> list[QueueMessage]: ...
    def ack(self, queue: str, msg: QueueMessage) -> None: ...
    def release(self, queue: str, msg: QueueMessage, delay_s: int = 0) -> None:
        """Trả message về hàng đợi (hiện lại sau delay_s)."""
        ...

    def depth(self, queue: str) -> int: ...


# ------------------------------------------------------------------ lưu file
@runtime_checkable
class BlobStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete_prefix(self, prefix: str) -> None: ...


# ------------------------------------------------------------------ secret
@runtime_checkable
class SecretStore(Protocol):
    def set(self, name: str, value: str) -> None: ...
    def get(self, name: str) -> str | None: ...
    def delete(self, name: str) -> None: ...


# ------------------------------------------------------------------ search
@dataclass
class IndexDoc:
    id: str
    doc_id: str
    doc_name: str
    item_code: str
    title: str
    page_from: int
    page_to: int
    content: str
    vector: list[float]
    enabled: bool = True


@dataclass
class SearchHit:
    id: str
    doc_id: str
    doc_name: str
    item_code: str
    title: str
    page_from: int
    page_to: int
    content: str
    score: float
    scores: dict[str, float] = field(default_factory=dict)


@runtime_checkable
class SearchIndex(Protocol):
    def ensure(self, dims: int) -> None: ...
    def upsert(self, docs: list[IndexDoc]) -> None: ...
    def delete_doc(self, doc_id: str) -> None: ...
    def set_enabled(self, doc_id: str, enabled: bool) -> None: ...
    def search(self, text: str, vector: list[float], k: int = 5) -> list[SearchHit]: ...
    def count(self) -> int: ...
    def health(self) -> None: ...


# ------------------------------------------------------------------ AI
@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    text: str
    images: list[bytes] = field(default_factory=list)  # PNG


@dataclass
class ChatResult:
    text: str
    usage: dict[str, int] = field(default_factory=dict)


@runtime_checkable
class LLM(Protocol):
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        json_mode: bool = False,
        tier: Literal["main", "mini", "vision"] = "main",
        max_tokens: int = 4096,
    ) -> ChatResult: ...
    def health(self) -> None: ...


@runtime_checkable
class Embedder(Protocol):
    dims: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def health(self) -> None: ...


@dataclass
class LayoutResult:
    markdown: str
    raw: dict = field(default_factory=dict)


@runtime_checkable
class LayoutAnalyzer(Protocol):
    """Azure Content Understanding (prebuilt-layout)."""

    def analyze(self, data: bytes, content_type: str = "application/pdf") -> LayoutResult: ...
    def health(self) -> None: ...
