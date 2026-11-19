"""Các step của khu A. Mỗi handler: đọc theo khoá docId+page+step, ghi đè kết quả, trả về step tiếp theo.

Live log chỉ ghi mã + tham số (id, trang, số đếm, điểm, lý do) — không ghi nội dung tài liệu.
"""

from __future__ import annotations

import json
import re

from app.domain.models import Chunk, ChunkStatus, DocStatus, PageStatus
from app.ports import ChatMessage, IndexDoc
from app.services import pipeline as pl
from app.services.config_service import NotConfigured
from app.services.jobs import Next, StepCtx, StepSkipped, register
from app.steps import rules
from app.steps.common import crop_png, k_page, k_source, render_page_png, single_page_pdf
from app.steps.docling_engine import analyze_page


def _page(ctx: StepCtx):
    p = ctx.c.repo.get_page(ctx.job.doc_id, ctx.job.page)
    if p is None:
        raise StepSkipped("page_not_found")
    return p


# ================================================================== 1. Docling
@register("docling", "docling")
def docling_step(ctx: StepCtx) -> list[Next]:
    c, n = ctx.c, ctx.job.page
    p = _page(ctx)
    p.status = PageStatus.docling
    c.repo.save_page(p)
    pdf = c.blob.get(k_source(p.doc_id))
    png, size = render_page_png(pdf, n, ctx.options.docling.images_scale)
    c.blob.put(k_page(p.doc_id, n, "image.png"), png, "image/png")
    a = analyze_page(pdf, n, ctx.options.docling)
    c.blob.put(k_page(p.doc_id, n, "docling.md"), a.markdown.encode(), "text/markdown")
    c.blob.put(
        k_page(p.doc_id, n, "docling.json"),
        json.dumps({"engine": a.engine, "image_size": size, "elements": a.elements}).encode(),
        "application/json",
    )
    p.engine, p.scores, p.features = a.engine, a.scores, a.features
    p.status, p.error, p.cu_status = PageStatus.routed, "", ""
    c.repo.save_page(p)
    ctx.emit(
        "docling.done",
        engine=a.engine,
        low_grade=a.scores.low_grade,
        low=a.scores.low_score,
        parse=a.scores.parse_score,
        tables=a.features.n_tables,
        figures=a.features.n_figures,
        removed=sum(a.features.removed.values()),
    )
    return [Next("route", n)]


# ================================================================== 2. Định tuyến
@register("route", "light")
def route_step(ctx: StepCtx) -> list[Next]:
    c, n = ctx.c, ctx.job.page
    p = _page(ctx)
    route, reasons = rules.decide_route(p, ctx.options.routing)
    p.route, p.route_reasons = route, reasons
    if route == "hard" and ctx.options.cu.enabled:
        p.status = PageStatus.cu
        c.repo.save_page(p)
        ctx.emit("route.decided", route=route, reasons=reasons)
        return [Next("cu", n)]
    p.status, p.cu_status = PageStatus.ready, ("" if route == "easy" else "skipped")
    c.repo.save_page(p)
    ctx.emit("route.decided", route=route, reasons=reasons)
    pl.maybe_stitch(c, p.doc_id)
    pl.refresh_doc(c, p.doc_id)
    return []


# ================================================================== 3. Content Understanding + vision
def _vision_figures(ctx: StepCtx, doc_id: str, n: int, llm) -> list[str]:
    meta = json.loads(ctx.c.blob.get(k_page(doc_id, n, "docling.json")))
    png = ctx.c.blob.get(k_page(doc_id, n, "image.png"))
    out = []
    for el in meta.get("elements", []):
        if el.get("label") != "picture" or el.get("removed") or el.get("area", 0) < ctx.options.routing.figure_min_area:
            continue
        ctx.check_cancelled()
        img = crop_png(png, el["bbox"])
        res = llm.chat(
            [ChatMessage("system", ctx.options.cu.vision_prompt), ChatMessage("user", "Convert this figure.", [img])],
            tier="vision",
        )
        out.append(f"<!-- figure:{el.get('figure', len(out))} -->\n{res.text.strip()}")
        ctx.emit("vision.figure", figure=el.get("figure"), tokens=res.usage.get("completion_tokens", 0))
    return out


@register("cu", "ai")
def cu_step(ctx: StepCtx) -> list[Next]:
    c, n = ctx.c, ctx.job.page
    p = _page(ctx)
    try:
        cu = ctx.adapter("cu")
    except NotConfigured:
        p.status, p.cu_status = PageStatus.ready, "skipped"
        c.repo.save_page(p)
        ctx.emit("cu.not_configured", "warn")
        pl.maybe_stitch(c, p.doc_id)
        pl.refresh_doc(c, p.doc_id)
        return []
    pdf = c.blob.get(k_source(p.doc_id))
    ctx.emit("cu.started")
    result = cu.analyze(single_page_pdf(pdf, n), "application/pdf")
    md = result.markdown.strip()
    if ctx.options.cu.figure_vision and p.features.n_figures:
        try:
            figs = _vision_figures(ctx, p.doc_id, n, ctx.adapter("llm"))
            if figs:
                md += "\n\n" + "\n\n".join(figs)
        except NotConfigured:
            ctx.emit("vision.not_configured", "warn")
    c.blob.put(k_page(p.doc_id, n, "cu.md"), (md + "\n").encode(), "text/markdown")
    c.blob.put(k_page(p.doc_id, n, "cu.json"), json.dumps(result.raw).encode(), "application/json")
    p.status, p.cu_status = PageStatus.ready, "done"
    c.repo.save_page(p)
    ctx.emit("cu.done", chars=len(md))
    pl.maybe_stitch(c, p.doc_id)
    pl.refresh_doc(c, p.doc_id)
    return []


# ================================================================== 4. Nối trang
@register("stitch", "light")
def stitch_step(ctx: StepCtx) -> list[Next]:
    c, doc = ctx.c, ctx.doc
    pages = c.repo.list_pages(doc.id)
    sources: dict[int, str] = {}
    for p in pages:
        if p.status in (PageStatus.review, PageStatus.approved) and p.current_version:
            sources[p.page] = pl.page_markdown(c, p)
            continue
        name = "cu.md" if p.cu_status == "done" else "docling.md"
        key = k_page(doc.id, p.page, name)
        sources[p.page] = c.blob.get(key).decode() if c.blob.exists(key) else ""
    res = rules.stitch_pages(sources, ctx.options.stitch)
    updated = 0
    for p in pages:
        p.continues_next = res.continues_next.get(p.page, False)
        p.table_continues_next = res.table_continues_next.get(p.page, False)
        if p.status == PageStatus.ready:
            c.blob.put(k_page(doc.id, p.page, "stitched.md"), res.texts[p.page].encode(), "text/markdown")
            p = pl.save_version(c, p, res.texts[p.page], "stitched", "system")
            p.status = PageStatus.review
            updated += 1
        c.repo.save_page(p)
    ctx.emit(
        "stitch.done",
        pages=updated,
        headers_removed=sum(res.removed.values()),
        joins=sum(res.continues_next.values()),
        table_joins=sum(res.table_continues_next.values()),
    )
    pl.refresh_doc(c, doc.id, DocStatus.ocr_review)
    pl.refresh_doc(c, doc.id)
    return []


# ================================================================== Review: LLM chạy lại theo prompt
@register("rerun", "ai", max_attempts=2)
def rerun_step(ctx: StepCtx) -> list[Next]:
    c, n = ctx.c, ctx.job.page
    p = _page(ctx)
    try:
        llm = ctx.adapter("llm")
    except NotConfigured as e:
        raise StepSkipped("llm_not_configured") from e
    png = c.blob.get(k_page(p.doc_id, n, "image.png"))
    current = pl.page_markdown(c, p)
    instruction = ctx.job.params.get("prompt") or "Fix OCR errors."
    res = llm.chat(
        [
            ChatMessage("system", ctx.options.review.rerun_prompt),
            ChatMessage("user", f"Instruction from reviewer:\n{instruction}\n\nCurrent Markdown:\n{current}", [png]),
        ],
        tier="vision",
        max_tokens=8000,
    )
    text = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", res.text.strip())
    p = c.repo.get_page(p.doc_id, n)
    pl.save_version(c, p, text + "\n", "llm", ctx.job.created_by, note="rerun")
    ctx.emit("rerun.done", v=p.current_version, tokens=res.usage.get("completion_tokens", 0))
    pl.refresh_doc(c, p.doc_id)
    return []


# ================================================================== 5. Agentic chunking
def _llm_spans(ctx: StepCtx, llm, sec: rules.Section) -> tuple[list[rules.ChunkSpan], int, dict]:
    opts = ctx.options.chunk
    numbered = "\n".join(f"{i}: {ln.text}" for i, ln in enumerate(sec.lines))
    feedback = ""
    best: tuple[list[rules.ChunkSpan], dict] | None = None
    for rnd in range(1, opts.max_rounds + 1):
        ctx.check_cancelled()
        user = (
            f"Section item code: {sec.item_code or '(none)'}\nTarget chunk size: about {opts.max_chars} "
            f"characters.\nLines 0..{len(sec.lines) - 1}:\n{numbered}"
        )
        if feedback:
            user += f"\n\nYour previous answer broke these rules, fix them:\n{feedback}"
        res = llm.chat([ChatMessage("system", opts.prompt), ChatMessage("user", user)], json_mode=True)
        try:
            data = json.loads(res.text)
            spans = [
                rules.ChunkSpan(
                    int(x["start"]),
                    int(x["end"]),
                    str(x.get("item_code") or sec.item_code),
                    str(x.get("title") or sec.title)[:120],
                )
                for x in data.get("chunks", [])
            ]
        except (ValueError, KeyError, TypeError, AttributeError):
            spans = []
        v = rules.validate_spans(sec.lines, spans, opts)
        hard = rules.hard_violations(v)
        ctx.emit(
            "chunk.round",
            item_code=sec.item_code,
            round=rnd,
            chunks=len(spans),
            violations=hard,
            codes=sorted({x for codes in v.values() for x in codes}),
        )
        if best is None or hard < rules.hard_violations(best[1]):
            best = (spans, v)
        if hard == 0:
            return spans, rnd, v
        feedback = "; ".join(f"chunk {i}: {', '.join(codes)}" if i >= 0 else ", ".join(codes) for i, codes in v.items())
    spans, v = best if best else ([], {-1: ["no_chunks"]})
    if -1 in v or not spans:
        spans = rules.deterministic_spans(sec, opts)
        v = rules.validate_spans(sec.lines, spans, opts)
        ctx.emit("chunk.fallback", "warn", item_code=sec.item_code)
    return spans, opts.max_rounds, v


def _llm_confidence(llm, text: str) -> float | None:
    prompt = (
        "Rate from 0 to 1 how well this chunk of a Japanese dental insurance document stands alone for "
        "retrieval: it names its item code, keeps conditions with exceptions, and is not cut mid-sentence "
        'or mid-table. Return JSON {"score": number}.'
    )
    try:
        res = llm.chat(
            [ChatMessage("system", prompt), ChatMessage("user", text[:6000])],
            json_mode=True,
            tier="mini",
            max_tokens=50,
        )
        return max(0.0, min(1.0, float(json.loads(res.text)["score"])))
    except Exception:  # noqa: BLE001 — điểm phụ, lỗi thì bỏ qua
        return None


@register("chunk", "ai", max_attempts=2)
def chunk_step(ctx: StepCtx) -> list[Next]:
    c, doc, opts = ctx.c, ctx.doc, ctx.options.chunk
    pages = sorted(c.repo.list_pages(doc.id), key=lambda p: p.page)
    texts = [(p.book_page, pl.page_markdown(c, p), p.continues_next, p.table_continues_next) for p in pages]
    lines = rules.assemble_lines(texts)
    sections = rules.rough_sections(lines, opts)
    ctx.emit("chunk.rough", sections=len(sections), lines=len(lines))
    llm = None
    if opts.llm_refine or opts.llm_confidence:
        try:
            llm = ctx.adapter("llm")
        except NotConfigured:
            ctx.emit("chunk.llm_not_configured", "warn")
    chunks: list[Chunk] = []
    for sec in sections:
        ctx.check_cancelled()
        if llm and opts.llm_refine and len(sec.lines) <= 400:
            spans, rounds, v = _llm_spans(ctx, llm, sec)
        else:
            spans, rounds = rules.deterministic_spans(sec, opts), 0
            v = rules.validate_spans(sec.lines, spans, opts)
        section_level = v.get(-1, [])
        for i, s in enumerate(spans):
            text = rules.span_text(sec.lines, s)
            if not text:
                continue
            viol = sorted(set(v.get(i, []) + section_level))
            rs = rules.rule_score(viol)
            ls = _llm_confidence(llm, text) if (llm and opts.llm_confidence) else None
            chunks.append(
                Chunk(
                    id=f"c{len(chunks) + 1:05d}",
                    doc_id=doc.id,
                    seq=len(chunks) + 1,
                    item_code=s.item_code,
                    title=s.title,
                    text=text,
                    page_from=sec.lines[s.start].page,
                    page_to=sec.lines[s.end].page,
                    rule_score=rs,
                    llm_score=ls,
                    confidence=round(rs if ls is None else (rs + ls) / 2, 3),
                    violations=viol,
                    rounds=rounds,
                )
            )
        ctx.emit(
            "chunk.section",
            item_code=sec.item_code,
            chunks=len(spans),
            rounds=rounds,
            violations=sum(len(x) for x in v.values()),
        )
    c.repo.replace_chunks(doc.id, chunks)
    ctx.emit("chunk.done", chunks=len(chunks), low_confidence=sum(1 for x in chunks if x.confidence < 0.7))
    pl.refresh_doc(c, doc.id, DocStatus.chunk_review)
    return []


# ================================================================== 6. Embedding + index
@register("index", "ai")
def index_step(ctx: StepCtx) -> list[Next]:
    c, doc = ctx.c, ctx.doc
    try:
        embedder, search = ctx.adapter("embedding"), ctx.adapter("search")
    except NotConfigured as e:
        raise StepSkipped(f"{e.component}_not_configured") from e
    chunks = [x for x in c.repo.list_chunks(doc.id) if x.status != ChunkStatus.draft]
    search.ensure(embedder.dims)
    search.delete_doc(doc.id)
    batch = max(1, ctx.options.index.embed_batch)
    done = 0
    for i in range(0, len(chunks), batch):
        ctx.check_cancelled()
        part = chunks[i : i + batch]
        vecs = embedder.embed([f"{x.item_code} {x.title}\n{x.text}" for x in part])
        search.upsert(
            [
                IndexDoc(
                    id=f"{doc.id}-{x.id}",
                    doc_id=doc.id,
                    doc_name=doc.name,
                    item_code=x.item_code,
                    title=x.title,
                    page_from=x.page_from,
                    page_to=x.page_to,
                    content=x.text,
                    vector=v,
                    enabled=doc.enabled,
                )
                for x, v in zip(part, vecs, strict=True)
            ]
        )
        done += len(part)
        ctx.emit("index.progress", done=done, total=len(chunks))
    for x in chunks:
        x.status = ChunkStatus.indexed
        c.repo.save_chunk(x)
    ctx.emit("index.done", chunks=len(chunks), dims=embedder.dims)
    pl.refresh_doc(c, doc.id, DocStatus.indexed)
    return []
