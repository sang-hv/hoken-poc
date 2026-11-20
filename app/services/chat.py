"""Chat thử với tài liệu đã index (khu B, bản test trong Admin UI).

Luồng: tìm hybrid (giống chatbot thật) → nếu không có đoạn đủ tốt thì chuyển CSKH ngay → LLM trả lời CHỈ từ các
đoạn tìm được, trích dẫn [n] → không có căn cứ thì cũng chuyển CSKH. Không lưu câu hỏi, không ghi nội dung vào log.
Service không import SDK cloud: dùng adapter qua `c.config.adapter(...)`.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from typing import Any

from app.domain.options import ChatOptions
from app.ports import ChatMessage, SearchHit

SOURCE_CHARS = 1800  # cắt mỗi đoạn gửi cho LLM


def build_messages(
    question: str, history: list[dict[str, str]], hits: list[SearchHit], opts: ChatOptions
) -> list[ChatMessage]:
    """System prompt + vài lượt trước + câu hỏi kèm các đoạn đánh số [1]..[n]."""
    msgs = [ChatMessage("system", opts.system_prompt)]
    for turn in history[-opts.max_history * 2 :] if opts.max_history > 0 else []:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            msgs.append(ChatMessage(turn["role"], str(turn["content"])[:4000]))
    sources = "\n\n".join(
        f"[{i}] {h.item_code or '-'} {h.title} ({h.doc_name} P{h.page_from}"
        f"{'' if h.page_to == h.page_from else f'-{h.page_to}'})\n{h.content[:SOURCE_CHARS]}"
        for i, h in enumerate(hits, start=1)
    )
    msgs.append(ChatMessage("user", f"Sources:\n{sources}\n\nQuestion: {question}"))
    return msgs


def parse_answer(text: str, n_sources: int) -> dict[str, Any]:
    """Đọc JSON LLM trả về; sai dạng thì coi chữ là câu trả lời và lấy trích dẫn [n] trong chữ."""
    try:
        data = json.loads(text)
        answer = str(data.get("answer") or "").strip()
        cited = [int(x) for x in data.get("cited") or [] if str(x).isdigit()]
        handoff = bool(data.get("handoff"))
    except (ValueError, TypeError, AttributeError):
        answer, cited, handoff = text.strip(), [], False
    cited += [int(m) for m in re.findall(r"\[(\d+)\]", answer)]
    cited = sorted({n for n in cited if 1 <= n <= n_sources})
    if not answer:
        handoff = True
    return {"answer": answer, "cited": cited, "handoff": handoff}


def ask(c, question: str, history: list[dict[str, str]], k: int | None = None) -> dict[str, Any]:
    """Trả lời một câu hỏi. Ném NotConfigured nếu chưa cấu hình embedding / search / LLM."""
    opts = c.config.pipeline()[1]
    k = k or opts.index.top_k
    t0 = time.monotonic()
    embedder, idx = c.config.adapter("embedding"), c.config.adapter("search")
    hits = idx.search(question, embedder.embed([question])[0], k)
    t_search = int((time.monotonic() - t0) * 1000)
    out: dict[str, Any] = {
        "sources": [asdict(h) for h in hits],
        "ms": {"search": t_search, "llm": 0},
        "usage": {},
        "config_version": c.config.pipeline()[0],
    }
    if not hits or hits[0].score < opts.chat.min_score:
        return {**out, "answer": "", "cited": [], "handoff": True, "reason": "no_source"}
    llm = c.config.adapter("llm")
    t1 = time.monotonic()
    res = llm.chat(build_messages(question, history, hits, opts.chat), json_mode=True, max_tokens=1200)
    out["ms"]["llm"] = int((time.monotonic() - t1) * 1000)
    out["usage"] = res.usage
    parsed = parse_answer(res.text, len(hits))
    return {**out, **parsed, "reason": "not_in_sources" if parsed["handoff"] else ""}
