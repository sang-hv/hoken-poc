"""Amazon OpenSearch: từ khoá (kuromoji) + k-NN vector, gộp RRF ở client. Ký SigV4 hoặc basic auth."""

from __future__ import annotations

import json

import httpx

from app.adapters.aws._session import session
from app.core.text import rrf
from app.ports import IndexDoc, SearchHit


class OpenSearchIndex:
    def __init__(self, cfg: dict, secrets: dict):
        self.endpoint = cfg["endpoint"].rstrip("/")
        self.index = cfg.get("index") or "hoken-chunks"
        self.region = cfg.get("region") or "ap-northeast-1"
        self.auth = cfg.get("auth", "iam_role")
        self.basic = (cfg.get("username", ""), secrets.get("password", ""))
        self.service = "aoss" if ".aoss." in self.endpoint else "es"
        self._creds = session(self.region, cfg, secrets).get_credentials() if self.auth != "basic" else None

    @classmethod
    def from_config(cls, cfg: dict, secrets: dict) -> OpenSearchIndex:
        return cls(cfg, secrets)

    def _req(self, method: str, path: str, body=None, ndjson: bool = False, ok404: bool = False) -> dict:
        url = f"{self.endpoint}{path}"
        data = body if isinstance(body, str | bytes) or body is None else json.dumps(body)
        if isinstance(data, str):
            data = data.encode()
        headers = {"Content-Type": "application/x-ndjson" if ndjson else "application/json"}
        auth = None
        if self.auth == "basic":
            auth = self.basic
        else:
            from botocore.auth import SigV4Auth
            from botocore.awsrequest import AWSRequest

            req = AWSRequest(method=method, url=url, data=data or b"", headers=headers)
            SigV4Auth(self._creds.get_frozen_credentials(), self.service, self.region).add_auth(req)
            headers = dict(req.headers)
        r = httpx.request(method, url, content=data, headers=headers, auth=auth, timeout=60)
        if ok404 and r.status_code == 404:
            return {}
        if r.status_code >= 400:
            raise RuntimeError(f"OpenSearch HTTP {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def ensure(self, dims: int) -> None:
        existing = self._req("GET", f"/{self.index}/_mapping", ok404=True)
        if existing:
            props = next(iter(existing.values()))["mappings"]["properties"]
            have = props.get("content_vector", {}).get("dimension")
            if have and have != dims:
                raise RuntimeError(f"Index có {have} chiều, embedding {dims} chiều — cần index lại")
            return
        self._req(
            "PUT",
            f"/{self.index}",
            {
                "settings": {
                    "index": {"knn": True},
                    "analysis": {
                        "analyzer": {
                            "ja": {
                                "type": "custom",
                                "tokenizer": "kuromoji_tokenizer",
                                "filter": ["kuromoji_baseform", "cjk_width", "lowercase"],
                            }
                        }
                    },
                },
                "mappings": {
                    "properties": {
                        "doc_id": {"type": "keyword"},
                        "doc_name": {"type": "keyword"},
                        "item_code": {"type": "keyword"},
                        "title": {"type": "text", "analyzer": "ja"},
                        "content": {"type": "text", "analyzer": "ja"},
                        "page_from": {"type": "integer"},
                        "page_to": {"type": "integer"},
                        "enabled": {"type": "boolean"},
                        "content_vector": {
                            "type": "knn_vector",
                            "dimension": dims,
                            "method": {"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil"},
                        },
                    }
                },
            },
        )

    def upsert(self, docs: list[IndexDoc]) -> None:
        for i in range(0, len(docs), 200):
            lines = []
            for d in docs[i : i + 200]:
                lines.append(json.dumps({"index": {"_index": self.index, "_id": d.id}}))
                lines.append(
                    json.dumps(
                        {
                            "doc_id": d.doc_id,
                            "doc_name": d.doc_name,
                            "item_code": d.item_code,
                            "title": d.title,
                            "content": d.content,
                            "page_from": d.page_from,
                            "page_to": d.page_to,
                            "enabled": d.enabled,
                            "content_vector": d.vector,
                        },
                        ensure_ascii=False,
                    )
                )
            res = self._req("POST", "/_bulk?refresh=true", "\n".join(lines) + "\n", ndjson=True)
            if res.get("errors"):
                raise RuntimeError("OpenSearch bulk có lỗi")

    def delete_doc(self, doc_id: str) -> None:
        self._req(
            "POST", f"/{self.index}/_delete_by_query?refresh=true", {"query": {"term": {"doc_id": doc_id}}}, ok404=True
        )

    def set_enabled(self, doc_id: str, enabled: bool) -> None:
        self._req(
            "POST",
            f"/{self.index}/_update_by_query?refresh=true",
            {
                "query": {"term": {"doc_id": doc_id}},
                "script": {"source": "ctx._source.enabled = params.e", "params": {"e": enabled}},
            },
            ok404=True,
        )

    def search(self, text: str, vector: list[float], k: int = 5) -> list[SearchHit]:
        n = max(k * 10, 50)
        src = ["doc_id", "doc_name", "item_code", "title", "content", "page_from", "page_to"]
        flt = [{"term": {"enabled": True}}]
        kw = self._req(
            "POST",
            f"/{self.index}/_search",
            {
                "size": n,
                "_source": src,
                "query": {
                    "bool": {
                        "filter": flt,
                        "should": [
                            {"match": {"content": text}},
                            {"match": {"title": text}},
                            {"term": {"item_code": {"value": text.strip(), "boost": 5}}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
            },
            ok404=True,
        )
        vec = self._req(
            "POST",
            f"/{self.index}/_search",
            {
                "size": n,
                "_source": src,
                "query": {"knn": {"content_vector": {"vector": vector, "k": n, "filter": {"bool": {"filter": flt}}}}},
            },
            ok404=True,
        )
        docs, kw_rank, vec_rank, kw_s, vec_s = {}, [], [], {}, {}
        for h in kw.get("hits", {}).get("hits", []):
            docs[h["_id"]], kw_s[h["_id"]] = h["_source"], h["_score"]
            kw_rank.append(h["_id"])
        for h in vec.get("hits", {}).get("hits", []):
            docs[h["_id"]], vec_s[h["_id"]] = h["_source"], h["_score"]
            vec_rank.append(h["_id"])
        out = []
        for key, score in sorted(rrf([vec_rank, kw_rank]).items(), key=lambda kv: -kv[1])[:k]:
            s = docs[key]
            out.append(
                SearchHit(
                    key,
                    s["doc_id"],
                    s.get("doc_name", ""),
                    s.get("item_code", ""),
                    s.get("title", ""),
                    s.get("page_from", 0),
                    s.get("page_to", 0),
                    s.get("content", ""),
                    score,
                    {"vector": float(vec_s.get(key, 0)), "keyword": float(kw_s.get(key, 0))},
                )
            )
        return out

    def count(self) -> int:
        return int(self._req("GET", f"/{self.index}/_count", ok404=True).get("count", 0))

    def health(self) -> None:
        self._req("GET", "/")
