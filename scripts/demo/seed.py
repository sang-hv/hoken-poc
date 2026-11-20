"""Seed dữ liệu GIẢ để test UI khu A (chỉ dev). Chạy qua pipeline thật với dịch vụ AI giả (scripts/demo/mock_ai.py).

Kết quả:
  - 3 người dùng: admin / reviewer / viewer @example.com, mật khẩu `password-1234`
  - Dịch vụ AI trỏ vào mock server (http://localhost:8100): LLM, embedding (local), CU (azure), search pgvector
  - 4 tài liệu ở các trạng thái: đã index · đang review chunk · đang review OCR · lỗi CU

Docling không có trong môi trường dev này nên điểm Docling được GIẢ LẬP (`fake_docling`) để màn định tuyến,
khung layout và lý do định tuyến có dữ liệu. Dừng worker nền trước khi chạy để seed tự xử lý job.

Chạy:
  NODE_PATH=$(npm root -g) node scripts/demo/make_pdfs.js out/demo
  .venv/bin/python -m uvicorn scripts.demo.mock_ai:app --port 8100 &
  .venv/bin/python -m scripts.demo.seed
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import app.steps.handlers as handlers
from app.core.util import hash_password, new_id, now_iso
from app.domain.models import PageFeatures, PageScores, Role, User
from app.services import chunks as chunk_svc
from app.services import jobs
from app.services import pipeline as pl
from app.services.container import get_container
from app.steps.docling_engine import PageAnalysis
from app.steps.rules import join_wrapped_lines

MOCK = "http://localhost:8100"
PDF_DIR = Path("out/demo")
PASSWORD = "password-1234"
CODE = re.compile(r"^(?:区分番号「)?([A-Z]\d{3}(?:-\d+){0,3})")


# ------------------------------------------------------------------ Docling giả lập
def _rects(pdf: bytes, page: int):
    """Rect chữ của pdfium (thường là từng ký tự) gom thành từng đoạn chữ trên cùng một dòng."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    p = doc[page - 1]
    w, h = p.get_size()
    tp = p.get_textpage()
    chars = []
    for i in range(tp.count_rects()):
        left, bottom, right, top = tp.get_rect(i)
        text = tp.get_text_bounded(left, bottom, right, top)
        if text.strip():
            chars.append((text.strip(), [left / w, 1 - top / h, right / w, 1 - bottom / h]))
    chars.sort(key=lambda c: (round((c[1][1] + c[1][3]) / 2, 2), c[1][0]))
    runs: list[list] = []
    for t, bb in chars:
        if runs:
            rt, rb = runs[-1]
            same_line = abs((rb[1] + rb[3]) / 2 - (bb[1] + bb[3]) / 2) < 0.008
            if same_line and 0 <= bb[0] - rb[2] < 0.025:
                runs[-1] = [rt + t, [rb[0], min(rb[1], bb[1]), bb[2], max(rb[3], bb[3])]]
                continue
        runs.append([t, list(bb)])
    return [(t, [round(x, 4) for x in bb]) for t, bb in runs]


def _union(boxes):
    return [
        min(b[0] for b in boxes) - 0.01,
        min(b[1] for b in boxes) - 0.01,
        max(b[2] for b in boxes) + 0.01,
        max(b[3] for b in boxes) + 0.01,
    ]


def fake_docling(pdf: bytes, page: int, opts) -> PageAnalysis:
    rects = _rects(pdf, page)
    texts = [t for t, _ in rects]
    joined = "\n".join(texts)
    feats = PageFeatures(has_text_layer=True)
    elements: list[dict] = []
    skip: set[int] = set()

    for i, (t, bb) in enumerate(rects):  # logo / con dấu → bị loại
        if t in ("SAMPLE", "確認"):
            cls = "logo" if t == "SAMPLE" else "stamp"
            feats.removed[cls] = feats.removed.get(cls, 0) + 1
            elements.append({"label": "picture", "class": cls, "bbox": _union([bb]), "removed": True})
            skip.add(i)
    fig_idx = [
        i
        for i, (t, _) in enumerate(rects)
        if t in ("初診・検査", "施設基準の届出あり？", "M015-2 を算定", "算定不可", "はい", "いいえ")
    ]
    if fig_idx:
        bb = _union([rects[i][1] for i in fig_idx])
        bb = [0.06, bb[1] - 0.02, 0.94, bb[3] + 0.02]
        area = round((bb[2] - bb[0]) * (bb[3] - bb[1]), 4)
        elements.append({"label": "picture", "class": "flow_chart", "bbox": bb, "figure": 0, "area": area})
        feats.n_figures, feats.max_figure_area = 1, area
        skip.update(fig_idx)
    t_start = next((i for i, (t, _) in enumerate(rects) if t.startswith("区分")), None)
    if t_start is not None:
        t_end = t_start
        for i in range(t_start + 1, len(rects)):
            if rects[i][0].startswith(("注", "なお", "(1)", "図")) or len(rects[i][0]) > 40:
                break
            t_end = i
        bb = _union([rects[i][1] for i in range(t_start, t_end + 1)])
        elements.append({"label": "table", "bbox": bb})
        feats.n_tables = 1
        table_text = "".join(rects[i][0] for i in range(t_start, t_end + 1))
        if any(x in table_text for x in ("前歯", "月1回目")):  # hàng tiêu đề con → bảng có ô gộp
            feats.complex_tables = 1
        feats.table_at_bottom, feats.table_at_top = bb[3] > 0.88, bb[1] < 0.12
        skip.update(range(t_start, t_end + 1))
    for i, (t, bb) in enumerate(rects):
        if i in skip or t.startswith("- ") or "サンプル" in t:
            continue
        elements.append({"label": "section_header" if CODE.match(t) else "text", "bbox": bb, "text": t})

    # Confidence theo phần tử (giả lập cụm layout của Docling): bảng gộp ô / hình thấp hơn, vài dòng có số 点
    # bị hạ để màn review có chỗ viền đỏ.
    for el in elements:
        if el.get("removed"):
            continue
        txt = el.get("text", "")
        h = sum(ord(ch) for ch in txt) if txt else 0
        if el["label"] == "table":
            el["confidence"] = 0.68 if feats.complex_tables else 0.86
        elif el["label"] == "picture":
            el["confidence"] = 0.77
        elif re.search(r"\d.*点", txt) and h % 3 == 0:
            el["confidence"] = round(0.6 + (h % 15) / 100, 2)
        else:
            el["confidence"] = round(0.88 + (h % 11) / 100, 2)

    # Điểm Docling giả lập: trang có bảng/hình → layout thấp hơn; một trang có lớp text "kém"
    seed = sum(ord(ch) for ch in joined) % 7
    parse = 0.62 if "I011" in joined else 0.93 + seed / 200
    layout = 0.74 if feats.n_tables or feats.n_figures else 0.9 + seed / 150
    scores = [s for s in (parse, layout) if s is not None]
    low, mean = min(scores), sum(scores) / len(scores)

    def grade(v):
        return "poor" if v < 0.5 else "fair" if v < 0.8 else "good" if v < 0.9 else "excellent"

    md_lines = [
        ln
        for ln in join_wrapped_lines(
            "\n".join(t for i, (t, _) in enumerate(rects) if i not in skip or i == (fig_idx[0] if fig_idx else -1))
        ).split("\n")
    ]
    md = "\n".join("<!-- figure:0 -->" if fig_idx and ln == rects[fig_idx[0]][0] else ln for ln in md_lines)
    md = "\n".join(f"## {ln}" if CODE.match(ln) else ln for ln in md.split("\n"))
    return PageAnalysis(
        "docling",
        md.strip() + "\n",
        PageScores(
            parse_score=round(parse, 3),
            layout_score=round(layout, 3),
            low_score=round(low, 3),
            mean_score=round(mean, 3),
            low_grade=grade(low),
            mean_grade=grade(mean),
        ),
        feats,
        elements,
    )


# ------------------------------------------------------------------ seed
def drain(c):
    jobs.run_worker(c, ["docling", "light", "ai"], drain=True, idle_exit_s=3, poll_s=0.2)


def upload(c, file: str, name: str, kind: str, book_page: int, actor: str):
    data = (PDF_DIR / file).read_bytes()
    doc = pl.create_document(
        c,
        data=data,
        filename=file,
        name=name,
        kind=kind,
        book_page_start=book_page,
        page_from=None,
        page_to=None,
        actor=actor,
    )
    drain(c)
    return c.repo.get_doc(doc.id)


def main() -> int:
    c = get_container()
    if c.settings.is_prod:
        print("Không seed dữ liệu giả trên prod", file=sys.stderr)
        return 1
    if not (PDF_DIR / "akahon_sample_536-543.pdf").exists():
        print("Chưa có PDF mẫu: NODE_PATH=$(npm root -g) node scripts/demo/make_pdfs.js out/demo", file=sys.stderr)
        return 1

    users = {}
    for email, name, role in (
        ("admin@example.com", "Admin", Role.admin),
        ("reviewer@example.com", "Sato Reviewer", Role.reviewer),
        ("viewer@example.com", "Tanaka Viewer", Role.viewer),
    ):
        u = c.repo.find_user_by_email(email) or User(id=new_id(), email=email, created_at=now_iso())
        u.name, u.role, u.password_hash, u.active = name, role, hash_password(PASSWORD), True
        users[role] = c.repo.save_user(u)
    admin, reviewer = users[Role.admin].email, users[Role.reviewer].email

    cfg = c.config
    cfg.update_provider(
        "llm",
        "local",
        {"base_url": f"{MOCK}/v1", "model": "mock-gpt", "mini_model": "mock-mini", "vision_model": "mock-vision"},
        {"api_key": "mock-key"},
        admin,
    )
    cfg.update_provider("embedding", "local", {"base_url": f"{MOCK}/v1", "model": "mock-embed", "dims": 256}, {}, admin)
    cfg.update_provider(
        "cu",
        "azure",
        {"endpoint": MOCK, "analyzer_id": "prebuilt-layout", "auth": "key"},
        {"api_key": "mock-key"},
        admin,
    )
    cfg.update_provider("search", "local", {"index": "hoken_chunks_demo"}, {}, admin)
    if cfg.pipeline()[0] == 0:
        _, opts = cfg.pipeline()
        cfg.update_pipeline(opts.model_dump(mode="json"), admin)

    handlers.analyze_page = fake_docling  # Docling giả lập (xem docstring)

    print("1/4 Tài liệu đã index …")
    d = upload(c, "akahon_sample_536-538_short.pdf", "赤本 サンプル P536–538（索引済み）", "akahon", 536, reviewer)
    for p in c.repo.list_pages(d.id):
        pl.submit_page(c, d.id, p.page, reviewer)
    pl.start_chunking(c, d.id, reviewer)
    drain(c)
    chunk_svc.approve_chunks(c, d.id, [x.id for x in c.repo.list_chunks(d.id)], True, reviewer)
    pl.start_index(c, d.id, reviewer)
    drain(c)

    print("2/4 Tài liệu đang review chunk …")
    d = upload(c, "midorihon_sample_372-375.pdf", "緑本 サンプル P372–375", "midorihon", 372, reviewer)
    for p in c.repo.list_pages(d.id):
        pl.submit_page(c, d.id, p.page, reviewer)
    pl.start_chunking(c, d.id, reviewer)
    drain(c)
    ch = c.repo.list_chunks(d.id)
    chunk_svc.approve_chunks(c, d.id, [x.id for x in ch[:2]], True, reviewer)

    print("3/4 Tài liệu đang review OCR …")
    d = upload(c, "akahon_sample_536-543.pdf", "赤本 サンプル P536–543", "akahon", 536, reviewer)
    p1 = c.repo.get_page(d.id, 1)
    pl.edit_page(c, d.id, 1, pl.page_markdown(c, p1).replace("1,200点", "1,200点（確認済み）"), reviewer, "fix")
    for n in (1, 2, 3):
        pl.submit_page(c, d.id, n, reviewer)
    pl.rerun_page_llm(c, d.id, 4, "表の2列目を確認してください", reviewer)
    drain(c)

    print("4/4 Tài liệu lỗi CU …")
    original = jobs.STEPS["cu"]

    def cu_fails(ctx):
        raise RuntimeError("CU HTTP 429: Too Many Requests (mock — quota exceeded)")

    jobs.STEPS["cu"] = jobs.StepDef("ai", cu_fails, 1)
    try:
        d = upload(c, "akahon_sample_failed.pdf", "赤本 サンプル P600–601（CU エラー）", "akahon", 600, reviewer)
        for p in c.repo.list_pages(d.id):
            pl.set_route_override(c, d.id, p.page, "force_cu", reviewer)
        drain(c)
    finally:
        jobs.STEPS["cu"] = original

    for doc in c.repo.list_docs():
        print(f"  {doc.status.value:<14} {doc.name}")
    print(f"\nĐăng nhập: admin@example.com / reviewer@example.com / viewer@example.com — mật khẩu {PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
