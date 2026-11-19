"""LLM / embedding qua server OpenAI-compatible (Ollama, vLLM, LM Studio...). Chỉ dùng cho dev."""

from __future__ import annotations

from app.adapters.openai_common import parse_chat, post_json, to_openai_messages
from app.ports import ChatMessage, ChatResult


class OpenAICompatLLM:
    def __init__(self, base_url: str, model: str, mini_model: str = "", vision_model: str = "", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.models = {"main": model, "mini": mini_model or model, "vision": vision_model or model}
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    @classmethod
    def from_config(cls, cfg: dict, secrets: dict) -> OpenAICompatLLM:
        return cls(
            cfg["base_url"],
            cfg["model"],
            cfg.get("mini_model", ""),
            cfg.get("vision_model", ""),
            secrets.get("api_key", ""),
        )

    def chat(self, messages: list[ChatMessage], *, json_mode=False, tier="main", max_tokens=4096) -> ChatResult:
        payload: dict = {
            "model": self.models[tier],
            "messages": to_openai_messages(messages),
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return parse_chat(post_json(f"{self.base_url}/chat/completions", self.headers, payload))

    def health(self) -> None:
        self.chat([ChatMessage("user", "ping")], max_tokens=5)


class OpenAICompatEmbedder:
    def __init__(self, base_url: str, model: str, dims: int, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dims = int(dims)
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    @classmethod
    def from_config(cls, cfg: dict, secrets: dict) -> OpenAICompatEmbedder:
        return cls(cfg["base_url"], cfg["model"], int(cfg.get("dims") or 1024), secrets.get("api_key", ""))

    def embed(self, texts: list[str]) -> list[list[float]]:
        data = post_json(f"{self.base_url}/embeddings", self.headers, {"model": self.model, "input": texts})
        vecs = [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
        if vecs and len(vecs[0]) != self.dims:
            raise RuntimeError(f"Embedding trả về {len(vecs[0])} chiều, cấu hình {self.dims}")
        return vecs

    def health(self) -> None:
        self.embed(["ping"])
