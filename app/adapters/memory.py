"""Adapter trong bộ nhớ — chỉ dùng cho test và chạy thử nhanh. Không có trong Admin UI."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
import time
from typing import Any

from app.core.text import keyword_score, keyword_terms, rrf
from app.ports import ChatMessage, ChatResult, IndexDoc, LayoutResult, QueueMessage, SearchHit


class MemoryStore:
    def __init__(self):
        self.data: dict[tuple[str, str], dict[str, dict]] = {}
        self.lock = threading.Lock()

    def get(self, coll, pk, id):
        d = self.data.get((coll, pk), {}).get(id)
        return copy.deepcopy(d) if d is not None else None

    def put(self, coll, pk, id, doc):
        with self.lock:
            self.data.setdefault((coll, pk), {})[id] = copy.deepcopy(doc)

    def create(self, coll, pk, id, doc):
        with self.lock:
            part = self.data.setdefault((coll, pk), {})
            if id in part:
                return False
            part[id] = copy.deepcopy(doc)
            return True

    def delete(self, coll, pk, id):
        with self.lock:
            self.data.get((coll, pk), {}).pop(id, None)

    def delete_partition(self, coll, pk):
        with self.lock:
            self.data.pop((coll, pk), None)

    def query(self, coll, pk, eq=None, id_gt=None, limit=1000, desc=False):
        items = sorted(self.data.get((coll, pk), {}).items(), reverse=desc)
        out = []
        for id, doc in items:
            if id_gt and id <= id_gt:
                continue
            if eq and any(doc.get(k) != v for k, v in eq.items()):
                continue
            out.append(copy.deepcopy(doc))
            if len(out) >= limit:
                break
        return out

    def health(self):
        return None


class MemoryQueue:
    def __init__(self):
        self.items: dict[str, list[dict]] = {}
        self.lock = threading.Lock()
        self.seq = 0

    def send(self, queue, body, delay_s=0):
        with self.lock:
            self.seq += 1
            self.items.setdefault(queue, []).append(
                {
                    "id": str(self.seq),
                    "body": json.loads(json.dumps(body)),
                    "visible": time.time() + delay_s,
                    "count": 0,
                }
            )

    def receive(self, queue, max_messages=1, visibility_s=900):
        now = time.time()
        out = []
        with self.lock:
            for it in self.items.get(queue, []):
                if it["visible"] <= now:
                    it["visible"] = now + visibility_s
                    it["count"] += 1
                    out.append(QueueMessage(it["id"], it["body"], it["id"], it["count"]))
                    if len(out) >= max_messages:
                        break
        return out

    def ack(self, queue, msg):
        with self.lock:
            self.items[queue] = [i for i in self.items.get(queue, []) if i["id"] != msg.receipt]

    def release(self, queue, msg, delay_s=0):
        with self.lock:
            for i in self.items.get(queue, []):
                if i["id"] == msg.receipt:
                    i["visible"] = time.time() + delay_s

    def depth(self, queue):
        return len(self.items.get(queue, []))


class MemoryBlob:
    def __init__(self):
        self.data: dict[str, bytes] = {}

    def put(self, key, data, content_type="application/octet-stream"):
        self.data[key] = bytes(data)

    def get(self, key):
        if key not in self.data:
            raise FileNotFoundError(key)
        return self.data[key]

    def exists(self, key):
        return key in self.data

    def delete_prefix(self, prefix):
        for k in [k for k in self.data if k.startswith(prefix)]:
            del self.data[k]


class MemorySecrets:
    def __init__(self):
        self.data: dict[str, str] = {}

    def set(self, name, value):
        self.data[name] = value

    def get(self, name):
        return self.data.get(name)

    def delete(self, name):
        self.data.pop(name, None)


class MemorySearch:
    def __init__(self):
        self.docs: dict[str, IndexDoc] = {}
        self.dims = 0

    @classmethod
    def from_config(cls, cfg, secrets):
        return cls()

    def ensure(self, dims):
        self.dims = dims

    def upsert(self, docs):
        for d in docs:
            self.docs[d.id] = d

    def delete_doc(self, doc_id):
        self.docs = {k: v for k, v in self.docs.items() if v.doc_id != doc_id}

    def set_enabled(self, doc_id, enabled):
        for d in self.docs.values():
            if d.doc_id == doc_id:
                d.enabled = enabled

    def search(self, text, vector, k=5):
        live = [d for d in self.docs.values() if d.enabled]
        vs = {d.id: _cos(vector, d.vector) for d in live}
        terms = keyword_terms(text)
        ks = {d.id: keyword_score(d.content, terms) for d in live}
        fused = rrf([sorted(vs, key=lambda i: -vs[i]), [i for i in sorted(ks, key=lambda i: -ks[i]) if ks[i] > 0]])
        out = []
        for i, s in sorted(fused.items(), key=lambda kv: -kv[1])[:k]:
            d = self.docs[i]
            out.append(
                SearchHit(
                    d.id,
                    d.doc_id,
                    d.doc_name,
                    d.item_code,
                    d.title,
                    d.page_from,
                    d.page_to,
                    d.content,
                    s,
                    {"vector": vs[i], "keyword": ks[i]},
                )
            )
        return out

    def count(self):
        return len(self.docs)

    def health(self):
        return None


def _cos(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b, strict=False)) / (na * nb)


class HashEmbedder:
    """Embedding giả: băm bigram ký tự vào vector. Đủ để test luồng, không dùng thật."""

    def __init__(self, dims: int = 64):
        self.dims = dims

    @classmethod
    def from_config(cls, cfg, secrets):
        return cls(int(cfg.get("dims") or 64))

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * self.dims
            for i in range(len(t) - 1):
                h = int(hashlib.md5(t[i : i + 2].encode()).hexdigest()[:8], 16)
                v[h % self.dims] += 1.0
            out.append(v)
        return out

    def health(self):
        return None


class ScriptedLLM:
    """LLM giả cho test: trả lời theo hàm `responder(messages, tier, json_mode) -> str`."""

    def __init__(self, responder=None):
        self.responder = responder or (lambda m, tier, j: "{}" if j else "ok")
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: list[ChatMessage], *, json_mode=False, tier="main", max_tokens=4096):
        self.calls.append({"tier": tier, "json": json_mode, "n_images": sum(len(m.images) for m in messages)})
        return ChatResult(self.responder(messages, tier, json_mode), {"prompt_tokens": 1, "completion_tokens": 1})

    def health(self):
        return None


class FakeLayout:
    def __init__(self, markdown: str = "# CU\n\nCU text"):
        self.markdown = markdown
        self.calls = 0

    def analyze(self, data, content_type="application/pdf"):
        self.calls += 1
        return LayoutResult(self.markdown, {"fake": True})

    def health(self):
        return None
