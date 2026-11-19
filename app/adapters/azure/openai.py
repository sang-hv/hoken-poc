"""Azure OpenAI (chat, vision, embedding) qua REST."""

from __future__ import annotations

from app.adapters.azure._auth import headers_for
from app.adapters.openai_common import parse_chat, post_json, to_openai_messages
from app.ports import ChatMessage, ChatResult

SCOPE = "https://cognitiveservices.azure.com/.default"


class AzureOpenAILLM:
    def __init__(self, cfg: dict, secrets: dict):
        self.endpoint = cfg["endpoint"].rstrip("/")
        self.deployments = {
            "main": cfg["deployment"],
            "mini": cfg.get("mini_deployment") or cfg["deployment"],
            "vision": cfg.get("vision_deployment") or cfg["deployment"],
        }
        self.api_version = cfg.get("api_version") or "2024-10-21"
        self.temperature = cfg.get("temperature")
        self.seed = cfg.get("seed")
        self.headers = headers_for(cfg, secrets, SCOPE)

    @classmethod
    def from_config(cls, cfg: dict, secrets: dict) -> AzureOpenAILLM:
        return cls(cfg, secrets)

    def chat(self, messages: list[ChatMessage], *, json_mode=False, tier="main", max_tokens=4096) -> ChatResult:
        url = (
            f"{self.endpoint}/openai/deployments/{self.deployments[tier]}/chat/completions"
            f"?api-version={self.api_version}"
        )
        payload: dict = {"messages": to_openai_messages(messages), "max_completion_tokens": max_tokens}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.temperature not in (None, ""):
            payload["temperature"] = float(self.temperature)
        if self.seed not in (None, ""):
            payload["seed"] = int(self.seed)
        return parse_chat(post_json(url, self.headers(), payload))

    def health(self) -> None:
        self.chat([ChatMessage("user", "ping")], max_tokens=16)


class AzureOpenAIEmbedder:
    def __init__(self, cfg: dict, secrets: dict):
        self.endpoint = cfg["endpoint"].rstrip("/")
        self.deployment = cfg["deployment"]
        self.dims = int(cfg.get("dims") or 1536)
        self.api_version = cfg.get("api_version") or "2024-10-21"
        self.headers = headers_for(cfg, secrets, SCOPE)

    @classmethod
    def from_config(cls, cfg: dict, secrets: dict) -> AzureOpenAIEmbedder:
        return cls(cfg, secrets)

    def embed(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.endpoint}/openai/deployments/{self.deployment}/embeddings?api-version={self.api_version}"
        data = post_json(url, self.headers(), {"input": texts, "dimensions": self.dims})
        return [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]

    def health(self) -> None:
        self.embed(["ping"])
