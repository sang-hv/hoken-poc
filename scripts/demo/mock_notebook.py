"""Mock LLM cho UI v2 — phần của A1 (chat Agentic RAG). Chỉ dev/test UI.

`answer(messages, json_mode)` nhận messages dạng OpenAI (dict) như mock_ai; trả chuỗi nếu nhận ra yêu cầu
của mình, None nếu không (mock_ai sẽ xử lý tiếp).

Giao thức agent (app/services/notebooks.py): lượt đầu → tìm bằng chính câu hỏi; chưa thấy đoạn nào đủ giống →
tìm lại bằng từ khoá; có đoạn giống → trả lời trích 2–3 dòng kèm [n]; hết cách → chuyển CSKH (handoff).
Không phải chất lượng trả lời thật."""

from __future__ import annotations

import json
import re

from app.core.text import keyword_terms
from app.services.notebooks import AGENT_MARK, FORCE_ANSWER, RESULTS_HEAD

MIN_OVERLAP = 3  # số cặp ký tự chung tối thiểu để coi là "có căn cứ"


def _text(m: dict) -> str:
    c = m.get("content") or ""
    return c if isinstance(c, str) else " ".join(p.get("text", "") for p in c if p.get("type") == "text")


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", "", text.lower())
    return {t[i : i + 2] for i in range(len(t) - 1)}


def _blocks(results: str) -> list[tuple[int, str, str]]:
    """[(n, dòng tiêu đề, nội dung)] từ một tin 'Search results for: ...'."""
    body = results.split("\n", 1)[1] if "\n" in results else ""
    body = body.split("\n\n" + FORCE_ANSWER, 1)[0]
    out = []
    for b in re.split(r"\n\n(?=\[\d+\] )", body):
        m = re.match(r"\[(\d+)\] (.*)", b)
        if m:
            head, _, content = b.partition("\n")
            out.append((int(m.group(1)), head, content))
    return out


def _lang(system: str, question: str) -> str:
    if "Answer language: English" in system:
        return "en"
    if "Answer language: Vietnamese" in system:
        return "vi"
    if "Answer language: Japanese" in system:
        return "ja"
    if re.search(r"[ぁ-んァ-ン一-龯]", question):
        return "ja"
    if re.search(r"[àáảãạăâđèéẻẽẹêìíỉĩịòóỏõọôơùúủũụưỳýỷỹỵ]", question.lower()):
        return "vi"
    return "en"


def _say(lang: str, label: str, quote: str, n: int) -> str:
    if lang == "en":
        return f"According to {label}: {quote} [{n}]"
    if lang == "vi":
        return f"Theo {label}: {quote} [{n}]"
    return f"{label} によると、{quote} [{n}]"


def answer(messages: list[dict], json_mode: bool) -> str | None:
    if not json_mode or not messages or AGENT_MARK not in _text(messages[0]):
        return None
    system = _text(messages[0])
    texts = [(m.get("role"), _text(m)) for m in messages]
    q_idx = max(i for i, (r, t) in enumerate(texts) if r == "user" and t.startswith("Question: "))
    question = texts[q_idx][1].removeprefix("Question: ")
    results = [t for r, t in texts[q_idx + 1 :] if r == "user" and t.startswith(RESULTS_HEAD)]
    queries = [t.split("\n", 1)[0].removeprefix(RESULTS_HEAD) for t in results]
    forced = bool(results) and FORCE_ANSWER in results[-1]
    if not results:
        return json.dumps({"action": "search", "query": question}, ensure_ascii=False)

    q = _bigrams(question)
    best: tuple[int, int, str, str] | None = None
    for res in results:
        for n, head, content in _blocks(res):
            score = len(q & _bigrams(head + content))
            if best is None or score > best[0]:
                best = (score, n, head, content)
    if best is None or best[0] < MIN_OVERLAP:
        retry = " ".join(keyword_terms(question)[:3])
        if not forced and retry and retry not in queries:
            return json.dumps({"action": "search", "query": retry}, ensure_ascii=False)
        return json.dumps({"action": "answer", "answer": "", "cited": [], "handoff": True})
    _, n, head, content = best
    label = re.sub(r"^\[\d+\] ", "", head)
    lines = [
        re.sub(r"\s*\|\s*", " ", ln).strip()
        for ln in content.split("\n")
        if ln.strip() and not ln.startswith(("|---", "#", "<!--"))
    ][:3]
    text = _say(_lang(system, question), label, " / ".join(lines), n)
    return json.dumps({"action": "answer", "answer": text, "cited": [n], "handoff": False}, ensure_ascii=False)
