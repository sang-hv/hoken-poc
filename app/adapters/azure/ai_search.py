"""Azure AI Search: hybrid (BM25 analyzer ja.microsoft + vector HNSW) + semantic ranker, qua REST."""

from __future__ import annotations

import httpx

from app.adapters.azure._auth import headers_for
from app.ports import IndexDoc, SearchHit

SCOPE = "https://search.azure.com/.default"


class AzureAISearch:
    def __init__(self, cfg: dict, secrets: dict):
        self.endpoint = cfg["endpoint"].rstrip("/")
        self.index = cfg.get("index") or "hoken-chunks"
        self.semantic = bool(cfg.get("semantic", True))
        self.api_version = cfg.get("api_version") or "2024-07-01"
        self.headers = headers_for(cfg, secrets, SCOPE)

    @classmethod
    def from_config(cls, cfg: dict, secrets: dict) -> AzureAISearch:
        return cls(cfg, secrets)

    def _req(self, method: str, path: str, json: dict | None = None, ok404: bool = False) -> dict:
        sep = "&" if "?" in path else "?"
        r = httpx.request(
            method,
            f"{self.endpoint}{path}{sep}api-version={self.api_version}",
            json=json,
            headers={**self.headers(), "Content-Type": "application/json"},
            timeout=60,
        )
        if ok404 and r.status_code == 404:
            return {}
        if r.status_code >= 400:
            raise RuntimeError(f"AI Search HTTP {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def ensure(self, dims: int) -> None:
        existing = self._req("GET", f"/indexes/{self.index}", ok404=True)
        if existing:
            vec = next((f for f in existing["fields"] if f["name"] == "content_vector"), None)
            if vec and vec.get("dimensions") != dims:
                raise RuntimeError(f"Index có {vec.get('dimensions')} chiều, embedding {dims} chiều — cần index lại")
            return
        body = {
            "name": self.index,
            "fields": [
                {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
                {"name": "doc_id", "type": "Edm.String", "filterable": True},
                {"name": "doc_name", "type": "Edm.String", "filterable": True},
                {
                    "name": "item_code",
                    "type": "Edm.String",
                    "filterable": True,
                    "searchable": True,
                    "analyzer": "keyword",
                },
                {"name": "title", "type": "Edm.String", "searchable": True, "analyzer": "ja.microsoft"},
                {"name": "page_from", "type": "Edm.Int32", "filterable": True},
                {"name": "page_to", "type": "Edm.Int32", "filterable": True},
                {"name": "content", "type": "Edm.String", "searchable": True, "analyzer": "ja.microsoft"},
                {"name": "enabled", "type": "Edm.Boolean", "filterable": True},
                {
                    "name": "content_vector",
                    "type": "Collection(Edm.Single)",
                    "searchable": True,
                    "dimensions": dims,
                    "vectorSearchProfile": "hnsw-profile",
                },
            ],
            "vectorSearch": {
                "algorithms": [{"name": "hnsw", "kind": "hnsw", "hnswParameters": {"metric": "cosine"}}],
                "profiles": [{"name": "hnsw-profile", "algorithm": "hnsw"}],
            },
            "semantic": {
                "configurations": [
                    {
                        "name": "default",
                        "prioritizedFields": {
                            "titleField": {"fieldName": "title"},
                            "prioritizedContentFields": [{"fieldName": "content"}],
                            "prioritizedKeywordsFields": [{"fieldName": "item_code"}],
                        },
                    }
                ]
            },
        }
        self._req("PUT", f"/indexes/{self.index}", body)

    def _actions(self, actions: list[dict]) -> None:
        for i in range(0, len(actions), 500):
            self._req("POST", f"/indexes/{self.index}/docs/index", {"value": actions[i : i + 500]})

    def upsert(self, docs: list[IndexDoc]) -> None:
        self._actions(
            [
                {
                    "@search.action": "mergeOrUpload",
                    "id": d.id,
                    "doc_id": d.doc_id,
                    "doc_name": d.doc_name,
                    "item_code": d.item_code,
                    "title": d.title,
                    "page_from": d.page_from,
                    "page_to": d.page_to,
                    "content": d.content,
                    "enabled": d.enabled,
                    "content_vector": d.vector,
                }
                for d in docs
            ]
        )

    def _ids(self, doc_id: str) -> list[str]:
        res = self._req(
            "POST",
            f"/indexes/{self.index}/docs/search",
            {"search": "*", "filter": f"doc_id eq '{doc_id.replace(chr(39), '')}'", "select": "id", "top": 1000},
            ok404=True,
        )
        return [v["id"] for v in res.get("value", [])]

    def delete_doc(self, doc_id: str) -> None:
        ids = self._ids(doc_id)
        if ids:
            self._actions([{"@search.action": "delete", "id": i} for i in ids])

    def set_enabled(self, doc_id: str, enabled: bool) -> None:
        ids = self._ids(doc_id)
        if ids:
            self._actions([{"@search.action": "merge", "id": i, "enabled": enabled} for i in ids])

    def search(self, text: str, vector: list[float], k: int = 5) -> list[SearchHit]:
        body: dict = {
            "search": text,
            "top": k,
            "filter": "enabled eq true",
            "select": "id,doc_id,doc_name,item_code,title,page_from,page_to,content",
            "vectorQueries": [{"kind": "vector", "vector": vector, "k": 50, "fields": "content_vector"}],
        }
        if self.semantic:
            body.update({"queryType": "semantic", "semanticConfiguration": "default"})
        res = self._req("POST", f"/indexes/{self.index}/docs/search", body, ok404=True)
        hits = []
        for v in res.get("value", []):
            score = v.get("@search.rerankerScore") or v.get("@search.score") or 0.0
            hits.append(
                SearchHit(
                    id=v["id"],
                    doc_id=v["doc_id"],
                    doc_name=v.get("doc_name", ""),
                    item_code=v.get("item_code", ""),
                    title=v.get("title", ""),
                    page_from=v.get("page_from", 0),
                    page_to=v.get("page_to", 0),
                    content=v.get("content", ""),
                    score=float(score),
                    scores={
                        "search": float(v.get("@search.score") or 0),
                        "reranker": float(v.get("@search.rerankerScore") or 0),
                    },
                )
            )
        return hits

    def count(self) -> int:
        sep_path = f"{self.endpoint}/indexes/{self.index}/docs/$count?api-version={self.api_version}"
        r = httpx.get(sep_path, headers=self.headers(), timeout=30)
        if r.status_code == 404:
            return 0
        r.raise_for_status()
        return int(r.text.strip().lstrip("﻿") or 0)

    def health(self) -> None:
        self._req("GET", "/indexes?$select=name")
