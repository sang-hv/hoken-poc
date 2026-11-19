"""Amazon Bedrock: chat/vision qua Converse API, embedding qua InvokeModel (Cohere / Titan)."""

from __future__ import annotations

import json
import re

from app.adapters.aws._session import session
from app.ports import ChatMessage, ChatResult


def _extract_json(text: str) -> str:
    m = re.search(r"\{.*\}", text, flags=re.S)
    return m.group(0) if m else text


class BedrockLLM:
    def __init__(self, cfg: dict, secrets: dict):
        self.client = session(cfg.get("region") or "ap-northeast-1", cfg, secrets).client("bedrock-runtime")
        self.models = {
            "main": cfg["model_id"],
            "mini": cfg.get("mini_model_id") or cfg["model_id"],
            "vision": cfg.get("vision_model_id") or cfg["model_id"],
        }
        self.temperature = cfg.get("temperature")

    @classmethod
    def from_config(cls, cfg: dict, secrets: dict) -> BedrockLLM:
        return cls(cfg, secrets)

    def chat(self, messages: list[ChatMessage], *, json_mode=False, tier="main", max_tokens=4096) -> ChatResult:
        system = [{"text": m.text} for m in messages if m.role == "system"]
        if json_mode:
            system.append({"text": "Respond with a single valid JSON object only."})
        conv = []
        for m in messages:
            if m.role == "system":
                continue
            content: list[dict] = [{"text": m.text}]
            content += [{"image": {"format": "png", "source": {"bytes": img}}} for img in m.images]
            conv.append({"role": m.role, "content": content})
        cfg: dict = {"maxTokens": max_tokens}
        if self.temperature not in (None, ""):
            cfg["temperature"] = float(self.temperature)
        res = self.client.converse(modelId=self.models[tier], messages=conv, system=system, inferenceConfig=cfg)
        text = "".join(p.get("text", "") for p in res["output"]["message"]["content"])
        usage = res.get("usage", {})
        return ChatResult(
            _extract_json(text) if json_mode else text,
            {"prompt_tokens": usage.get("inputTokens", 0), "completion_tokens": usage.get("outputTokens", 0)},
        )

    def health(self) -> None:
        self.chat([ChatMessage("user", "ping")], max_tokens=16)


class BedrockEmbedder:
    def __init__(self, cfg: dict, secrets: dict):
        self.client = session(cfg.get("region") or "ap-northeast-1", cfg, secrets).client("bedrock-runtime")
        self.model = cfg["model_id"]
        self.dims = int(cfg.get("dims") or 1024)

    @classmethod
    def from_config(cls, cfg: dict, secrets: dict) -> BedrockEmbedder:
        return cls(cfg, secrets)

    def _invoke(self, body: dict) -> dict:
        res = self.client.invoke_model(
            modelId=self.model, body=json.dumps(body), contentType="application/json", accept="application/json"
        )
        return json.loads(res["body"].read())

    def embed(self, texts: list[str]) -> list[list[float]]:
        if "cohere" in self.model:
            out = []
            for i in range(0, len(texts), 96):
                data = self._invoke({"texts": texts[i : i + 96], "input_type": "search_document", "truncate": "END"})
                emb = data["embeddings"]
                out += emb["float"] if isinstance(emb, dict) else emb
            return out
        return [self._invoke({"inputText": t, "dimensions": self.dims, "normalize": True})["embedding"] for t in texts]

    def health(self) -> None:
        v = self.embed(["ping"])[0]
        if len(v) != self.dims:
            raise RuntimeError(f"Model trả về {len(v)} chiều, cấu hình {self.dims}")
