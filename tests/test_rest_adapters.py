"""Kiểm tra request/response của adapter gọi REST (Azure OpenAI, CU, AI Search) bằng HTTP giả."""

from __future__ import annotations

import json

import httpx
import pytest

from app.ports import ChatMessage, IndexDoc


class FakeHttp:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[httpx.Request] = []

    def request(self, method, url, **kw):
        content = kw.get("content")
        if kw.get("json") is not None:
            content = json.dumps(kw["json"]).encode()
        req = httpx.Request(method, url, headers=kw.get("headers"), content=content)
        self.calls.append(req)
        resp = self.handler(req)
        resp.request = req
        return resp

    def install(self, monkeypatch):
        monkeypatch.setattr(httpx, "request", self.request)
        monkeypatch.setattr(httpx, "post", lambda url, **kw: self.request("POST", url, **kw))
        monkeypatch.setattr(httpx, "get", lambda url, **kw: self.request("GET", url, **kw))


def test_azure_openai_chat_and_embedding(monkeypatch):
    from app.adapters.azure.openai import AzureOpenAIEmbedder, AzureOpenAILLM

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        if req.url.path.endswith("/embeddings"):
            assert body["dimensions"] == 4
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]}]})
        assert req.headers["api-key"] == "k"
        assert "/deployments/gpt-mini/" in req.url.path
        assert body["response_format"] == {"type": "json_object"} and body["seed"] == 7
        assert body["messages"][1]["content"][1]["type"] == "image_url"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}},
        )

    FakeHttp(handler).install(monkeypatch)
    cfg = {
        "endpoint": "https://x.openai.azure.com",
        "deployment": "gpt",
        "mini_deployment": "gpt-mini",
        "auth": "key",
        "seed": 7,
    }
    llm = AzureOpenAILLM.from_config(cfg, {"api_key": "k"})
    res = llm.chat([ChatMessage("system", "s"), ChatMessage("user", "u", [b"png"])], json_mode=True, tier="mini")
    assert res.text == "{}" and res.usage["prompt_tokens"] == 3
    emb = AzureOpenAIEmbedder.from_config({**cfg, "deployment": "emb", "dims": 4}, {"api_key": "k"})
    assert emb.embed(["a"]) == [[0.1, 0.2, 0.3, 0.4]]


def test_content_understanding_polls_operation(monkeypatch):
    from app.adapters.azure.cu import ContentUnderstanding

    state = {"polls": 0}

    def handler(req: httpx.Request):
        if req.method == "POST":
            assert req.url.path.endswith("/analyzers/prebuilt-layout:analyzeBinary")
            assert req.headers["Ocp-Apim-Subscription-Key"] == "k"
            assert req.headers["content-type"] == "application/pdf"
            return httpx.Response(202, headers={"operation-location": "https://cu/op/1"}, json={})
        state["polls"] += 1
        if state["polls"] < 2:
            return httpx.Response(200, json={"status": "Running"})
        return httpx.Response(200, json={"status": "Succeeded", "result": {"contents": [{"markdown": "# 表\n| a |"}]}})

    FakeHttp(handler).install(monkeypatch)
    monkeypatch.setattr("time.sleep", lambda s: None)
    cu = ContentUnderstanding.from_config(
        {"endpoint": "https://r.services.ai.azure.com", "auth": "key"}, {"api_key": "k"}
    )
    res = cu.analyze(b"%PDF", "application/pdf")
    assert res.markdown == "# 表\n| a |" and state["polls"] == 2


def test_azure_ai_search_index_and_hybrid_query(monkeypatch):
    from app.adapters.azure.ai_search import AzureAISearch

    seen: dict[str, dict] = {}

    def handler(req: httpx.Request):
        path = req.url.path
        if req.method == "GET" and path == "/indexes/hoken-chunks":
            return httpx.Response(404, json={})
        body = json.loads(req.content) if req.content else {}
        seen[f"{req.method} {path}"] = body
        if path.endswith("/docs/search"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "d-c1",
                            "doc_id": "d",
                            "doc_name": "赤本",
                            "item_code": "M015-2",
                            "title": "",
                            "page_from": 536,
                            "page_to": 536,
                            "content": "x",
                            "@search.score": 0.5,
                            "@search.rerankerScore": 2.9,
                        }
                    ]
                },
            )
        return httpx.Response(200, json={})

    FakeHttp(handler).install(monkeypatch)
    s = AzureAISearch.from_config({"endpoint": "https://s.search.windows.net", "auth": "key"}, {"api_key": "k"})
    s.ensure(4)
    idx = seen["PUT /indexes/hoken-chunks"]
    vec = next(f for f in idx["fields"] if f["name"] == "content_vector")
    assert vec["dimensions"] == 4 and idx["semantic"]["configurations"][0]["name"] == "default"
    s.upsert([IndexDoc("d-c1", "d", "赤本", "M015-2", "", 536, 536, "x", [0.0] * 4)])
    assert seen["POST /indexes/hoken-chunks/docs/index"]["value"][0]["@search.action"] == "mergeOrUpload"
    hits = s.search("CAD/CAM", [0.0] * 4, 5)
    q = seen["POST /indexes/hoken-chunks/docs/search"]
    assert q["queryType"] == "semantic" and q["filter"] == "enabled eq true" and q["vectorQueries"][0]["k"] == 50
    assert hits[0].item_code == "M015-2" and hits[0].score == 2.9


def test_bedrock_converse_payload(monkeypatch):
    pytest.importorskip("boto3")
    from app.adapters.aws.bedrock import BedrockLLM

    captured = {}

    class FakeClient:
        def converse(self, **kw):
            captured.update(kw)
            return {
                "output": {"message": {"content": [{"text": 'Sure: {"score": 0.8}'}]}},
                "usage": {"inputTokens": 5, "outputTokens": 2},
            }

    llm = BedrockLLM.__new__(BedrockLLM)
    llm.client, llm.models, llm.temperature = FakeClient(), {"main": "m", "mini": "mm", "vision": "mv"}, 0
    res = llm.chat([ChatMessage("system", "sys"), ChatMessage("user", "u", [b"png"])], json_mode=True, tier="vision")
    assert res.text == '{"score": 0.8}'
    assert captured["modelId"] == "mv" and captured["messages"][0]["content"][1]["image"]["format"] == "png"
    assert captured["system"][0]["text"] == "sys" and captured["inferenceConfig"]["temperature"] == 0.0
