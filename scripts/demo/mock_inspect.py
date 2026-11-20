"""Mock LLM cho UI v2 — phần của A2 (VLM đọc lại phần tử, chấm trang, insights). Chỉ dev/test UI.

`answer(messages, json_mode)` nhận messages dạng OpenAI (dict) như mock_ai; trả chuỗi nếu nhận ra yêu cầu
của mình (prompt có dấu `[hoken:element-reread]` / `[hoken:page-score]` / `[hoken:insights]` — xem
app/services/inspect.py), None nếu không (mock_ai sẽ xử lý tiếp). Kết quả cố định theo nội dung, không phải
chất lượng thật."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

CODE = re.compile(r"[A-Z]\d{3}(?:-\d+){0,3}")


def _h(text: str) -> int:
    return int(hashlib.md5(text.encode()).hexdigest()[:8], 16)


def _text(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, str):
        return c
    return " ".join(p.get("text", "") for p in c or [] if p.get("type") == "text")


def _table(lines: list[str]) -> str:
    """Dòng chữ cách nhau bởi khoảng trắng / '|' → bảng Markdown; dòng đầu không có số = hàng tiêu đề."""
    rows = [[x for x in re.split(r"\s*\|\s*|\s+", ln.strip()) if x] for ln in lines if ln.strip()]
    rows = [r for r in rows if r]
    if not rows:
        return ""
    head = rows.pop(0) if len(rows) > 1 and not re.search(r"[0-9０-９]", "".join(rows[0])) else []
    n = max([len(r) for r in rows] + [len(head), 2])
    head = (head or ["区分", "点数"]) + [""] * n
    rows = [r + [""] * (n - len(r)) for r in rows]
    out = ["| " + " | ".join(head[:n]) + " |", "|" + "---|" * n]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def _reread(user: str) -> str:
    label = (re.search(r"Region type: (\S+)", user) or [None, "text"])[1]
    current = user.split("Current text:\n", 1)[-1].split("\n\nInstruction from reviewer:", 1)[0].strip()
    if current == "(empty)":
        current = ""
    lines = [ln for ln in current.split("\n") if ln.strip() and not ln.strip().startswith("<!--")]
    if label == "table":
        md = current if lines and all(ln.strip().startswith("|") for ln in lines) else _table(lines)
        md = md or "| 区分 | 点数 |\n|---|---|\n| （読み取り不可） | |"
    elif label == "picture":
        names = [re.sub(r"[`#|>]", "", ln).strip() for ln in lines][:4]
        if len(names) >= 2:
            md = "```mermaid\nflowchart TD\n" + "\n".join(
                f"  N{i}[{a}] --> N{i + 1}[{b}]" for i, (a, b) in enumerate(zip(names, names[1:], strict=False))
            )
            md += "\n```"
        else:
            md = "図：算定の流れを示すフローチャート（mock VLM による説明）"
    else:
        md = (
            unicodedata.normalize("NFKC", "\n".join(lines)) if lines else "（mock VLM：この領域の文字を読み取りました）"
        )
        if label == "section_header" and not md.startswith("#"):
            md = "## " + md
    conf = round(0.86 + (_h(current) % 12) / 100, 2)
    return json.dumps({"markdown": md, "confidence": conf}, ensure_ascii=False)


def _score(user: str) -> str:
    md = user.split("Extracted Markdown:\n", 1)[-1]
    s = 78 + _h(md) % 20
    if "|" not in md and "点" in md:
        s -= 8
    comments = ["表の列がずれている可能性があります。", "数字（点数）は画像と一致しています。", "全体的に良好です。"]
    return json.dumps({"score": s, "comment": comments[_h(md) % 3]}, ensure_ascii=False)


def _insights(user: str) -> str:
    codes = list(dict.fromkeys(CODE.findall(user)))[:6]
    heads = [ln.lstrip("# ").strip() for ln in user.split("\n") if ln.startswith("#")][:6]
    points = heads or [f"{c} の算定要件" for c in codes] or ["本文の要点（mock）"]
    summary = (
        "本資料は歯科診療報酬（保険点数）の算定方法をまとめた公開資料です。"
        + (f"主な区分は {', '.join(codes)} です。" if codes else "")
        + "各項目の点数、算定条件、例外（ただし書き）が記載されています。（mock LLM による要約）"
    )
    return json.dumps({"summary": summary, "key_points": points}, ensure_ascii=False)


def answer(messages: list[dict], json_mode: bool) -> str | None:
    system = " ".join(_text(m) for m in messages if m.get("role") == "system")
    user = _text(messages[-1]) if messages else ""
    if "[hoken:element-reread]" in system:
        return _reread(user)
    if "[hoken:page-score]" in system:
        return _score(user)
    if "[hoken:insights]" in system:
        return _insights(user)
    return None
