"""Phần dùng chung cho API dạng OpenAI (Azure OpenAI và các server OpenAI-compatible)."""

from __future__ import annotations

import base64
import time

import httpx

from app.ports import ChatMessage, ChatResult


def to_openai_messages(messages: list[ChatMessage]) -> list[dict]:
    out = []
    for m in messages:
        if not m.images:
            out.append({"role": m.role, "content": m.text})
            continue
        parts: list[dict] = [{"type": "text", "text": m.text}]
        for img in m.images:
            b64 = base64.b64encode(img).decode()
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        out.append({"role": m.role, "content": parts})
    return out


def post_json(url: str, headers: dict, payload: dict, timeout: float = 300, retries: int = 4) -> dict:
    """POST có retry cho 429/5xx (tôn trọng Retry-After)."""
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            r = httpx.post(url, headers=headers, json=payload, timeout=timeout)
        except httpx.TransportError:
            if attempt == retries:
                raise
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            wait = float(r.headers.get("retry-after", delay))
            time.sleep(min(wait, 60))
            delay *= 2
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json()
    raise RuntimeError("unreachable")


def parse_chat(data: dict) -> ChatResult:
    choice = data["choices"][0]["message"]
    usage = data.get("usage") or {}
    return ChatResult(
        text=choice.get("content") or "",
        usage={
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
        },
    )
