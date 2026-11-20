"""Server AI GIẢ cho dev/test UI — KHÔNG dùng cho đánh giá thật.

Giả lập đúng giao thức mà adapter thật đang gọi, để luồng chạy qua code adapter thật:
  - OpenAI-compatible: POST /v1/chat/completions, POST /v1/embeddings  (adapter llm/embedding "local")
  - Azure Content Understanding: POST /contentunderstanding/analyzers/{id}:analyzeBinary + poll  (adapter cu "azure")

Chạy: .venv/bin/python -m uvicorn scripts.demo.mock_ai:app --port 8100
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="MOCK AI (dev only)")
_ops: dict[str, dict] = {}
CODE = re.compile(r"[A-Z]\d{3}(?:-\d+){0,3}")
EXC = ("ただし", "なお", "この場合", "注")


def _h(text: str) -> int:
    return int(hashlib.md5(text.encode()).hexdigest()[:8], 16)


# ------------------------------------------------------------------ embeddings
@app.post("/v1/embeddings")
async def embeddings(req: Request):
    body = await req.json()
    texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
    dims = int(body.get("dimensions") or 256)
    data = []
    for i, t in enumerate(texts):
        v = [0.0] * dims
        for j in range(len(t) - 1):
            v[_h(t[j : j + 2]) % dims] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        data.append({"index": i, "embedding": [x / n for x in v], "object": "embedding"})
    return {"data": data, "model": body.get("model", "mock"), "usage": {"prompt_tokens": 1, "total_tokens": 1}}


# ------------------------------------------------------------------ chat
def _split(lines: list[str], code: str) -> list[dict]:
    """Chia hợp lệ: theo đoạn trống, không cắt bảng, ngoại lệ đi cùng đoạn trước."""
    chunks: list[dict] = []
    start, size = 0, 0
    for i, ln in enumerate(lines):
        size += len(ln)
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        boundary = nxt is not None and (not ln.strip()) and size > 160
        if boundary and nxt.strip().startswith("|"):
            boundary = True
        if boundary and nxt.strip().startswith(EXC):
            boundary = False
        if boundary and ln.strip().startswith("|"):
            boundary = False
        if boundary:
            chunks.append({"start": start, "end": i, "item_code": code, "title": ""})
            start, size = i + 1, 0
    chunks.append({"start": start, "end": len(lines) - 1, "item_code": code, "title": ""})
    return chunks


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", "", text)
    return {t[i : i + 2] for i in range(len(t) - 1)}


def _chat_rag(user: str) -> str:
    """Giả lập chatbot: chọn đoạn trùng nhiều cặp ký tự với câu hỏi nhất, trích 2 dòng đầu kèm [n]; không đoạn
    nào đủ giống → chuyển CSKH. Chỉ để test UI, không phải chất lượng trả lời thật."""
    body, _, question = user.rpartition("\n\nQuestion: ")
    blocks = re.split(r"\n\n(?=\[\d+\] )", body.removeprefix("Sources:\n"))
    q = _bigrams(question)
    scored = []
    for b in blocks:
        m = re.match(r"\[(\d+)\] (\S+)", b)
        if m:
            scored.append((len(q & _bigrams(b)), int(m.group(1)), m.group(2), b.split("\n", 1)[-1]))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < 3:
        return json.dumps({"answer": "", "cited": [], "handoff": True}, ensure_ascii=False)
    _, n, code, content = scored[0]
    lines = [
        re.sub(r"\s*\|\s*", " ", ln).strip()
        for ln in content.split("\n")
        if ln.strip() and not ln.startswith(("|---", "#", "| 列"))
    ][:3]
    answer = f"{code} によると、" + " / ".join(lines) + f" [{n}]"
    cited = [n]
    if len(scored) > 1 and scored[1][0] >= 3:
        answer += f"（関連: {scored[1][2]} [{scored[1][1]}]）"
        cited.append(scored[1][1])
    return json.dumps({"answer": answer, "cited": cited, "handoff": False}, ensure_ascii=False)


def _chat_answer(messages: list[dict], json_mode: bool) -> str:
    from scripts.demo import mock_inspect  # UI v2: tab 検査 (đọc lại, chấm điểm, insights)

    for mod in (mock_inspect,):
        out = mod.answer(messages, json_mode)
        if out is not None:
            return out

    def text_of(m):
        c = m["content"]
        return c if isinstance(c, str) else " ".join(p.get("text", "") for p in c if p.get("type") == "text")

    system = " ".join(text_of(m) for m in messages if m["role"] == "system")
    user = text_of(messages[-1])
    has_image = any(
        isinstance(m["content"], list) and any(p.get("type") == "image_url" for p in m["content"]) for m in messages
    )
    if json_mode and "Lines 0.." in user:
        code = re.search(r"Section item code: (\S+)", user).group(1)
        code = "" if code == "(none)" else code
        body = user.split(":\n", 1)[1].split("\n\nYour previous answer", 1)[0]
        lines = [re.sub(r"^\d+: ", "", ln) for ln in body.split("\n")]
        first_round = "previous answer broke" not in user
        if first_round and _h(code) % 2 == 0 and len(lines) > 2:
            # Vòng đầu cố tình bỏ sót dòng cuối → bộ kiểm tra luật bắt lỗi "coverage", agent sửa ở vòng 2
            return json.dumps({"chunks": [{"start": 0, "end": len(lines) - 2, "item_code": code}]})
        return json.dumps({"chunks": _split(lines, code or (CODE.search(lines[0]) or [""])[0])})
    if json_mode and "dental insurance (保険点数) assistant" in system:
        return _chat_rag(user)
    if json_mode and "Rate from 0 to 1" in system:
        return json.dumps({"score": round(0.55 + (_h(user) % 41) / 100, 2)})
    if has_image and "Current Markdown" in user:
        current = user.split("Current Markdown:\n", 1)[1]
        return current.rstrip() + "\n\n<!-- mock LLM: đã chạy lại theo yêu cầu của reviewer -->\n"
    if has_image:
        return (
            "```mermaid\nflowchart TD\n  A[初診・検査] --> B{施設基準の届出あり？}\n"
            "  B -- はい --> C[M015-2 を算定]\n  B -- いいえ --> D[算定不可]\n```"
        )
    return "pong"


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    json_mode = (body.get("response_format") or {}).get("type") == "json_object"
    text = _chat_answer(body["messages"], json_mode)
    return {
        "id": f"mock-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "model": body.get("model", "mock"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": max(1, len(text) // 2)},
    }


# ------------------------------------------------------------------ Content Understanding
def _cu_markdown(pdf: bytes) -> str:
    import pypdfium2 as pdfium

    from app.steps.rules import join_wrapped_lines

    doc = pdfium.PdfDocument(pdf)
    out = []
    for page in doc:
        lines = [ln.strip() for ln in page.get_textpage().get_text_range().replace("\r", "").split("\n")]
        lines = [ln for ln in join_wrapped_lines("\n".join(lines)).split("\n") if ln.strip()]
        # Giả lập CU bỏ header/footer trang (dòng tiêu đề tài liệu mẫu và số trang)
        lines = [ln for ln in lines if "サンプル" not in ln and not re.fullmatch(r"[-\s]*\d+[-\s]*", ln)]
        rows: list[str] = []
        for ln in lines:
            if CODE.match(ln):
                out += rows + ["", f"## {ln}", ""]
                rows = []
            elif re.search(r"\d[\d,]*点\s+\S", ln) or re.search(r"\S+\s+\d[\d,]*点$", ln) and len(ln) < 40:
                cells = ln.split()
                if not rows:
                    rows = [
                        "| " + " | ".join(f"列{i + 1}" for i in range(len(cells))) + " |",
                        "|" + "---|" * len(cells),
                    ]
                rows.append("| " + " | ".join(cells) + " |")
            else:
                out += rows + ([""] if rows else []) + [ln]
                rows = []
        out += rows
    return "\n".join(out).strip() + "\n"


def _cu_pages(pdf: bytes, markdown: str) -> list[dict]:
    """Giả lập `pages[].words[]` của prebuilt-layout: mỗi từ có `confidence`, `source` D(trang,8 số toạ độ inch)
    và `span` trỏ vào markdown. Confidence giả lập cố định theo nội dung; vài từ có số/点 bị hạ thấp để UI có
    chỗ viền đỏ."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    out = []
    for n, page in enumerate(doc, start=1):
        w, h = page.get_size()
        tp = page.get_textpage()
        chars = []
        for i in range(tp.count_rects()):
            left, bottom, right, top = tp.get_rect(i)
            text = tp.get_text_bounded(left, bottom, right, top)
            if text.strip():
                chars.append((text.strip(), left, h - top, right, h - bottom))
        chars.sort(key=lambda c: (round((c[2] + c[4]) / 2 / 4), c[1]))
        runs: list[list] = []  # gom rect cùng dòng, sát nhau thành một đoạn
        for t, x0, y0, x1, y1 in chars:
            if runs:
                r = runs[-1]
                if abs((r[2] + r[4]) / 2 - (y0 + y1) / 2) < 4 and 0 <= x0 - r[3] < 12:
                    runs[-1] = [r[0] + t, r[1], min(r[2], y0), x1, max(r[4], y1)]
                    continue
            runs.append([t, x0, y0, x1, y1])
        # Tìm span trên markdown đã bỏ khoảng trắng (text PDF và markdown khác nhau ở dấu cách) rồi đổi lại offset
        # (bỏ cả hàng tiêu đề "| 列1 | 列2 |" mà mock tự thêm — chữ đó không có trong PDF)
        fake = {i for m in re.finditer(r"^\|[ 列\d|]*$", markdown, re.M) for i in range(m.start(), m.end())}
        keep = [i for i, ch in enumerate(markdown) if not ch.isspace() and i not in fake]
        md_ns = "".join(markdown[i] for i in keep)
        words, cursor = [], 0
        for t, x0, y0, x1, y1 in runs:
            tokens = t.split()
            total = max(1, sum(len(k) for k in tokens))
            pos = 0
            for tok in tokens:
                a = x0 + (x1 - x0) * pos / total
                b = x0 + (x1 - x0) * (pos + len(tok)) / total
                pos += len(tok)
                hv = _h(tok)
                conf = 0.9 + (hv % 100) / 1000
                if re.search(r"[\d点]", tok) and hv % 4 == 0:
                    conf = 0.55 + (hv % 20) / 100
                at = md_ns.find(tok, cursor)
                word = {
                    "content": tok,
                    "confidence": round(conf, 3),
                    "source": "D({},{})".format(n, ",".join(f"{v / 72:.4f}" for v in (a, y0, b, y0, b, y1, a, y1))),
                }
                if at >= 0:
                    start, end = keep[at], keep[at + len(tok) - 1] + 1
                    word["span"] = {"offset": start, "length": end - start}
                    cursor = at + len(tok)
                words.append(word)
        out.append({"pageNumber": n, "width": round(w / 72, 4), "height": round(h / 72, 4), "words": words})
    return out


@app.post("/contentunderstanding/analyzers/{rest:path}")
async def cu_analyze(rest: str, req: Request):
    data = await req.body()
    op = uuid.uuid4().hex
    md = _cu_markdown(data)
    _ops[op] = {"ready_at": time.time() + 1.5, "markdown": md, "pages": _cu_pages(data, md)}
    base = str(req.base_url).rstrip("/")
    return JSONResponse(
        {"id": op, "status": "Running"},
        status_code=202,
        headers={"operation-location": f"{base}/contentunderstanding/analyzerResults/{op}"},
    )


@app.get("/contentunderstanding/analyzerResults/{op}")
async def cu_result(op: str):
    o = _ops.get(op)
    if not o:
        return JSONResponse({"error": "not found"}, status_code=404)
    if time.time() < o["ready_at"]:
        return {"id": op, "status": "Running"}
    content = {"markdown": o["markdown"], "kind": "document", "unit": "inch", "pages": o["pages"]}
    return {"id": op, "status": "Succeeded", "result": {"contents": [content]}}


@app.get("/contentunderstanding/analyzers/{analyzer}")
async def cu_get(analyzer: str):
    return {"analyzerId": analyzer, "status": "ready", "mock": True}
