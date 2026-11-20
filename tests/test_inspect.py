"""UI v2 — tab 検査: dựng phần tử (Docling / CU / pdfium), thứ tự đọc, điểm yếu, điểm chất lượng, sửa / đọc lại /
xác nhận phần tử và các endpoint."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.adapters.memory import ScriptedLLM
from app.domain.options import QualityOptions
from app.services import inspect as svc
from app.services import pipeline as pl
from app.services.jobs import run_worker
from app.steps import elements as E
from app.steps import rules
from app.steps.common import k_page

H = {"X-Requested-With": "hoken"}
Q = QualityOptions()


def _el(label="text", text="abc", **kw):
    return {"label": label, "bbox": [0.1, 0.1, 0.9, 0.2], "text": text, "raw_text": text, "confidence": None} | kw


def _codes(flags):
    return [f["code"] for f in flags]


# ================================================================== điểm yếu & điểm (thuần)
def test_weak_flags_rules():
    assert rules.element_weak_flags(_el(confidence=0.95), Q) == []
    low = rules.element_weak_flags(_el(confidence=0.7), Q)
    assert low == [{"code": "low_confidence", "severity": "warn", "detail": "0.70"}]
    assert rules.element_weak_flags(_el(confidence=0.5), Q)[0]["severity"] == "error"
    assert _codes(rules.element_weak_flags(_el("picture", "<!-- figure:0 -->"), Q)) == ["picture_no_desc"]
    assert rules.element_weak_flags(_el("picture", "<!-- figure:0 -->\n```mermaid\nA-->B\n```"), Q) == []
    assert _codes(rules.element_weak_flags(_el(text="", raw_text="M015-2 crown 1,200 points"), Q)) == ["missing_text"]
    # header/footer bị bỏ khi nối trang: không phải điểm yếu
    assert rules.element_weak_flags(_el("page_header", "", raw_text="Dental fee header", confidence=0.3), Q) == []
    assert rules.element_weak_flags(_el(reread_from=0.5, confidence=0.9), Q) == [
        {"code": "reread", "severity": "warn", "detail": "0.50"}
    ]


def test_table_suspect_reasons():
    ok = "| a | b |\n|---|---|\n| 1 | 2 |"
    assert rules.table_suspect_reason(_el("table", ok)) == ""
    assert rules.table_suspect_reason(_el("table", "a b\n1 2")) == "not_table"
    assert rules.table_suspect_reason(_el("table", "| a | b |\n|---|---|\n| 1 | 2 | 3 |")) == "cols"
    assert rules.table_suspect_reason(_el("table", ok, merged_cells=True)) == "merged"
    bottom = _el("table", ok, bbox=[0.1, 0.7, 0.9, 0.95])
    assert rules.table_suspect_reason(bottom, continues_next=True) == "cross_page"
    assert rules.table_suspect_reason(bottom) == ""


def test_page_level_flags_and_status():
    assert rules.page_level_flag([], "  \n", Q, scanned=False, ocr_score=None)["code"] == "blank_page"
    assert rules.page_level_flag([], "M015-2 text", Q, scanned=False, ocr_score=None) is None
    weak = rules.page_level_flag([], "M015-2 text", Q, scanned=True, ocr_score=0.5)
    assert weak == {"code": "ocr_weak", "severity": "warn", "detail": "0.50"}
    by_conf = rules.page_level_flag([_el(confidence=0.6)], "M015-2 text", Q, scanned=True, ocr_score=None)
    assert by_conf["code"] == "ocr_weak"
    assert rules.element_status([{"code": "x"}]) == "weak"
    assert rules.element_status([]) == "ok"
    assert rules.element_status([{"code": "x"}], "accepted") == "accepted"


def test_quality_scores_and_grades():
    good = [_el(confidence=0.95, status="ok", weak=[])]
    assert rules.page_quality_score(good) == 95
    weak = [_el(confidence=0.5, status="weak", weak=[{"code": "low_confidence", "severity": "error"}])]
    assert rules.page_quality_score(weak) == 38  # 50 − 12
    weak[0]["status"] = "fixed"  # đã sửa → confidence tính 1.0, không phạt
    assert rules.page_quality_score(weak) == 100
    assert rules.page_quality_score(good, vlm_score=75) == 85
    assert rules.page_quality_score([]) == 100
    assert rules.doc_quality_score([100, 100, 40]) == 68  # 0.7·80 + 0.3·40
    assert rules.doc_quality_score([]) == 0
    assert [rules.quality_grade(s, Q) for s in (90, 85, 70, 59)] == ["good", "good", "fair", "poor"]


# ================================================================== dựng phần tử (thuần)
def test_reading_order_rows_and_columns():
    els = [
        {"id": "right", "bbox": [0.55, 0.2, 0.9, 0.3]},
        {"id": "footer", "bbox": [0.4, 0.95, 0.6, 0.97]},
        {"id": "left2", "bbox": [0.1, 0.32, 0.45, 0.4]},
        {"id": "title", "bbox": [0.1, 0.05, 0.9, 0.1]},
        {"id": "left1", "bbox": [0.1, 0.2, 0.45, 0.3]},
    ]
    assert [e["id"] for e in E.reading_order(els)] == ["title", "left1", "right", "left2", "footer"]


def test_md_units_keep_tables_code_and_figures_together():
    md = "## M015-2 crown\ntext line\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n<!-- figure:0 -->\n```mermaid\nA-->B\n```\n"
    units = E.md_units(md)
    assert [u.kind for u in units] == ["line", "line", "table", "figure"]
    assert [u.sep for u in units] == ["", "\n", "\n\n", "\n\n"]
    assert units[3].figure == 0 and "mermaid" in units[3].text


def test_build_from_docling_like_elements():
    meta = {
        "engine": "docling",
        "elements": [
            {"label": "picture", "class": "logo", "bbox": [0.8, 0.0, 0.9, 0.05], "removed": True},
            {"label": "table", "bbox": [0.1, 0.4, 0.9, 0.6], "text": "区分 点数 初診 264点", "confidence": 0.68},
            {"label": "section_header", "bbox": [0.1, 0.1, 0.5, 0.13], "text": "M015-2 CAD/CAM冠", "confidence": 0.95},
            {
                "label": "text",
                "bbox": [0.1, 0.15, 0.9, 0.2],
                "text": "1歯につき 1,200点を算定する。",
                "confidence": 0.91,
            },
            {"label": "picture", "bbox": [0.1, 0.65, 0.9, 0.85], "figure": 0, "confidence": 0.77},
            {"label": "ocr_text", "bbox": [0.12, 0.16, 0.3, 0.19], "confidence": 0.4, "text": "1歯"},
        ],
    }
    md = (
        "## M015-2 CAD/CAM冠\n\n1歯につき 1,200点を算定する。\n\n"
        "| 区分 | 点数 |\n|---|---|\n| 初診 | 264点 |\n\n<!-- figure:0 -->\n"
    )
    els = E.build_page_elements(markdown=md, docling_meta=meta, complex_tables=1)
    assert [(e["id"], e["label"]) for e in els] == [
        ("e1", "section_header"),
        ("e2", "text"),
        ("e3", "table"),
        ("e4", "picture"),
    ]
    assert els[0]["text"] == "## M015-2 CAD/CAM冠"
    assert els[2]["text"].startswith("| 区分") and els[2]["merged_cells"] is True
    assert els[3]["text"] == "<!-- figure:0 -->"
    assert els[1]["confidence"] == 0.4  # ô OCR thấp trong vùng kéo confidence xuống
    assert all(e["source"] == "docling" for e in els)
    assert E.rebuild_markdown(els) == md


def _cu_raw():
    # trang 10 x 10 inch; polygon D(1, x1,y1, x2,y2, x3,y3, x4,y4)
    def src(x0, y0, x1, y1):
        return f"D(1,{x0},{y0},{x1},{y0},{x1},{y1},{x0},{y1})"

    return {
        "result": {
            "contents": [
                {
                    "markdown": "...",
                    "pages": [
                        {
                            "width": 10,
                            "height": 10,
                            "words": [
                                {"content": "M015-2", "confidence": 0.95, "source": src(1, 1, 3, 1.4)},
                                {"content": "初診料は", "confidence": 0.9, "source": src(1, 2, 3, 2.4)},
                                {"content": "264点", "confidence": 0.3, "source": src(3.1, 2, 4, 2.4)},
                                {"content": "初診", "confidence": 0.99, "source": src(1, 5, 2, 5.4)},
                            ],
                        }
                    ],
                    "paragraphs": [
                        {"role": "sectionHeading", "content": "M015-2", "source": src(1, 1, 3, 1.4)},
                        {"content": "初診料は 264点", "source": src(1, 2, 4, 2.4)},
                        {"role": "pageNumber", "content": "12", "source": src(5, 9.5, 5.5, 9.7)},
                        {"content": "初診", "source": src(1, 5, 2, 5.4)},
                    ],
                    "tables": [
                        {
                            "rowCount": 1,
                            "columnCount": 2,
                            "source": src(1, 4.9, 6, 5.5),
                            "cells": [{"content": "初診", "rowSpan": 2}, {"content": "264点"}],
                        }
                    ],
                }
            ]
        }
    }


def test_build_from_cu_like_result():
    md = "## M015-2\n\n初診料は 264点\n\n| 初診 | 264点 |\n|---|---|\n"
    els = E.build_page_elements(markdown=md, cu_raw=_cu_raw())
    assert [(e["label"], e["source"]) for e in els] == [
        ("section_header", "cu"),
        ("text", "cu"),
        ("table", "cu"),
        ("page_footer", "cu"),
    ]
    text = els[1]
    assert text["text"] == "初診料は 264点"
    assert text["confidence"] == round(0.7 * 0.6 + 0.3 * 0.3, 3)  # 0.7·mean + 0.3·min của từ trong vùng
    assert els[2]["merged_cells"] is True and els[2]["bbox"] == [0.1, 0.49, 0.6, 0.55]
    assert els[3]["text"] == ""  # số trang đã bị bỏ khi nối trang


def test_build_from_pdfium_lines(sample_pdf):
    toks = E.pdfium_tokens(sample_pdf, 1)
    md = "M015-2 CAD/CAM crown\nThe crown is calculated per tooth 1,200 points.\nConditions apply to molars only.\n"
    els = E.build_page_elements(markdown=md, tokens=toks)
    labels = [(e["label"], e["text"]) for e in els]
    assert labels[0] == ("page_header", "")  # header lặp lại đã bị bỏ khi nối trang
    assert labels[1] == ("section_header", "M015-2 CAD/CAM crown")
    assert labels[2][0] == "text" and labels[2][1].startswith("The crown")
    assert all(e["source"] == "pdfium" and e["confidence"] is None for e in els)
    assert [e["id"] for e in els] == [f"e{i}" for i in range(1, len(els) + 1)]
    assert E.rebuild_markdown(els) == md
    assert all(0 <= v <= 1 for e in els for v in e["bbox"])


def test_pdfium_heuristic_labels():
    def line(text, y, cells=None, h=0.012):
        ln = E.TextLine([E.Tok(text, [0.1, y, 0.6, y + h])])
        ln.cells = cells or [text]
        return ln

    lines = [
        line("目次", 0.02),
        line("第1章 初診料 ........ 12", 0.1),
        line("第2章 再診料 ........ 15", 0.12),
        line("M015-2 CAD/CAM冠", 0.2),
        line("区分 点数 備考", 0.3, ["区分", "点数", "備考"]),
        line("初診 264点 なし", 0.32, ["初診", "264点", "なし"]),
        line("・ただし書きの例", 0.5),
        line("注1 費用は所定点数に含まれる", 0.8),
        line("- 12 -", 0.9),
    ]
    blocks = E.blocks_from_lines(lines, "pdfium")
    assert [b["label"] for b in blocks] == [
        "page_header",
        "toc",
        "section_header",
        "table",
        "list",
        "footnote",
        "page_footer",
    ]
    assert blocks[3]["raw_text"] == "区分 | 点数 | 備考\n初診 | 264点 | なし"


def test_align_merges_joined_lines_and_unmatched_follow_previous():
    els = [
        {"label": "text", "bbox": [0.1, 0.1, 0.9, 0.12], "raw_text": "長い文章の前半部分で", "source": "docling"},
        {"label": "text", "bbox": [0.1, 0.13, 0.9, 0.15], "raw_text": "後半部分が続きます。", "source": "docling"},
    ]
    out = E.align(els, "長い文章の前半部分で後半部分が続きます。\n<!-- note -->\n")
    assert len(out) == 1 and out[0]["bbox"] == [0.1, 0.1, 0.9, 0.15]
    assert out[0]["text"] == "長い文章の前半部分で後半部分が続きます。\n<!-- note -->"


# ================================================================== service + API
@pytest.fixture
def client(container):
    from app.api.server import create_app

    with TestClient(create_app()) as cl:
        yield cl


def _admin(client):
    r = client.post("/api/setup", json={"email": "admin@example.com", "password": "password-123"}, headers=H)
    assert r.status_code == 200, r.text


def _upload(client, container, pdf) -> str:
    r = client.post("/api/documents", files={"file": ("s.pdf", pdf, "application/pdf")}, data={"name": "S"}, headers=H)
    assert r.status_code == 200, r.text
    run_worker(container, ["docling", "light", "ai"], drain=True, idle_exit_s=0, poll_s=0)
    return r.json()["id"]


def _vlm(messages, tier, json_mode):
    system = messages[0].text
    if svc.REREAD_MARK in system:
        return json.dumps({"markdown": "| 区分 | 点数 |\n|---|---|\n| 初診 | 264点 |", "confidence": 0.93})
    if svc.SCORE_MARK in system:
        return json.dumps({"score": 70, "comment": "表の列を確認"})
    if svc.INSIGHTS_MARK in system:
        return json.dumps({"summary": "歯科点数の資料。", "key_points": ["M015-2: 1,200点", "A000: 264点"]})
    return "{}" if json_mode else "ok"


def test_elements_endpoint_lazy_build_and_contract(client, container, sample_pdf):
    _admin(client)
    doc_id = _upload(client, container, sample_pdf)
    r = client.get(f"/api/documents/{doc_id}/pages/1/elements")
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data) == {"page", "book_page", "image_size", "score", "grade", "elements"}
    assert data["page"] == 1 and 0 <= data["score"] <= 100 and data["grade"] in ("good", "fair", "poor")
    el = data["elements"][0]
    assert set(el) == {*svc.PUBLIC}
    assert [e["order"] for e in data["elements"]] == list(range(1, len(data["elements"]) + 1))
    assert container.blob.exists(k_page(doc_id, 1, svc.ELEMENTS))
    sec = next(e for e in data["elements"] if e["label"] == "section_header")
    assert sec["text"] == "M015-2 CAD/CAM crown"
    assert client.get(f"/api/documents/{doc_id}/pages/1/elements/{sec['id']}/image").headers["content-type"] == (
        "image/png"
    )
    raw = client.get(f"/api/documents/{doc_id}/pages/1/elements/{sec['id']}/raw").json()
    assert raw["raw_text"] == "M015-2 CAD/CAM crown" and raw["source"] == "pdfium"
    assert client.get(f"/api/documents/{doc_id}/pages/1/elements/e99/raw").status_code == 404
    assert client.get(f"/api/documents/{doc_id}/pages/9/elements").status_code == 404
    assert client.get("/api/documents/nope/pages/1/elements").json()["detail"]["code"] == "doc_not_found"


def test_page_not_ready_is_404(client, container, sample_pdf):
    _admin(client)
    r = client.post("/api/documents", files={"file": ("s.pdf", sample_pdf, "application/pdf")}, headers=H)
    doc_id = r.json()["id"]  # chưa chạy worker → trang chưa có nội dung
    r = client.get(f"/api/documents/{doc_id}/pages/1/elements")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "page_not_ready"
    assert client.get(f"/api/documents/{doc_id}/quality").json()["pages"] == []
    assert svc.doc_quality(container, doc_id) is None


def test_edit_element_saves_version_and_rebuilds_markdown(client, container, sample_pdf):
    _admin(client)
    doc_id = _upload(client, container, sample_pdf)
    els = client.get(f"/api/documents/{doc_id}/pages/1/elements").json()["elements"]
    sec = next(e for e in els if e["label"] == "section_header")
    v_before = container.repo.get_page(doc_id, 1).current_version
    r = client.put(
        f"/api/documents/{doc_id}/pages/1/elements/{sec['id']}", json={"text": "## M015-2 CAD/CAM冠"}, headers=H
    )
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["status"] == "fixed" and e["source"] == "manual" and e["edited_by"] == "admin@example.com"
    p = container.repo.get_page(doc_id, 1)
    assert p.current_version == v_before + 1 and p.versions[-1].source == "element_edit"
    md = pl.page_markdown(container, p)
    assert md.startswith("## M015-2 CAD/CAM冠\nThe crown is calculated")
    # GET lần nữa không dựng lại (md_version khớp) → giữ trạng thái fixed
    again = client.get(f"/api/documents/{doc_id}/pages/1/elements").json()["elements"]
    assert next(x for x in again if x["id"] == sec["id"])["status"] == "fixed"
    hist = client.get(f"/api/documents/{doc_id}/pages/1/history").json()
    assert hist[0]["kind"] == "element_edit" and hist[0]["element_id"] == sec["id"]
    assert "CAD/CAM" not in hist[0]["summary"]  # chỉ id/nguồn/điểm, không chép nội dung
    assert any(h["kind"] == "page_version" and "stitched" in h["summary"] for h in hist)
    audit = [a for a in container.repo.list_audit() if a.action == "element.edit"]
    assert audit and "CAD" not in json.dumps(audit[0].detail)
    # Markdown đổi từ màn review cũ → phần tử được gán lại, phần tử không đổi nội dung giữ trạng thái
    pl.edit_page(container, doc_id, 1, md.replace("molars", "molar teeth"), "admin@example.com")
    again = client.get(f"/api/documents/{doc_id}/pages/1/elements").json()["elements"]
    assert next(x for x in again if x["id"] == sec["id"])["status"] == "fixed"
    assert any("molar teeth" in x["text"] for x in again)


def test_accept_reread_fix_weak_score_insights(client, container, sample_pdf):
    _admin(client)
    doc_id = _upload(client, container, sample_pdf)
    # Bảng đọc ra không phải bảng Markdown → table_suspect; một phần tử confidence thấp
    state = svc.load_state(container, container.repo.get_doc(doc_id), container.repo.get_page(doc_id, 3))
    tgt = next(e for e in state["elements"] if e["label"] == "text")
    tgt["label"], tgt["confidence"] = "table", 0.55
    svc.assess(container, container.repo.get_doc(doc_id), container.repo.get_page(doc_id, 3), state)
    svc._save_state(container, doc_id, 3, state)
    weak = client.get(f"/api/documents/{doc_id}/weak").json()
    mine = [w for w in weak if w["page"] == 3 and w["element_id"] == tgt["id"]]
    assert {w["code"] for w in mine} == {"low_confidence", "table_suspect"}
    assert set(mine[0]) == {"page", "element_id", "order", "label", "code", "severity", "status", "preview"}
    q = client.get(f"/api/documents/{doc_id}/quality").json()
    assert q["counts"]["low_confidence"] >= 1 and q["weak_open"] >= 2 and q["worst_page"]["page"] == 3
    assert svc.open_weak_pages(container, doc_id) == {3}

    # Chưa cấu hình LLM → 409
    r = client.post(f"/api/documents/{doc_id}/pages/3/elements/{tgt['id']}/reread", json={}, headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "llm_not_configured"

    # Xác nhận: hết điểm yếu mở, không tạo phiên bản mới (Markdown không đổi)
    v0 = container.repo.get_page(doc_id, 3).current_version
    r = client.post(f"/api/documents/{doc_id}/pages/3/elements/{tgt['id']}/accept", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert container.repo.get_page(doc_id, 3).current_version == v0
    assert svc.open_weak_pages(container, doc_id) == set()

    llm = ScriptedLLM(_vlm)
    container.config.overrides["llm"] = llm
    r = client.post(f"/api/documents/{doc_id}/pages/3/elements/{tgt['id']}/reread", json={"prompt": "表"}, headers=H)
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["source"] == "vlm" and e["status"] == "fixed" and e["text"].startswith("| 区分")
    assert e["confidence"] == 0.93 and "reread" in _codes(e["weak"])
    p = container.repo.get_page(doc_id, 3)
    assert p.versions[-1].source == "element_reread" and "| 初診 | 264点 |" in pl.page_markdown(container, p)
    assert llm.calls[-1]["tier"] == "vision" and llm.calls[-1]["n_images"] == 1

    # fix-weak: đọc lại mọi phần tử weak (chạy nền sau khi trả lời)
    state = svc.load_state(container, container.repo.get_doc(doc_id), container.repo.get_page(doc_id, 2))
    state["elements"][1]["confidence"] = 0.5
    svc.assess(container, container.repo.get_doc(doc_id), container.repo.get_page(doc_id, 2), state)
    svc._save_state(container, doc_id, 2, state)
    r = client.post(f"/api/documents/{doc_id}/fix-weak", headers=H)
    assert r.status_code == 200 and r.json() == {"queued": 1}
    assert svc.open_weak_pages(container, doc_id) == set()

    # AIで採点: body {} → 5 trang điểm thấp nhất (ở đây 3 trang)
    r = client.post(f"/api/documents/{doc_id}/score", json={}, headers=H)
    scored = r.json()["scored"]
    assert len(scored) == 3 and scored[0] == {
        "page": scored[0]["page"],
        "score": 70,
        "grade": "fair",
        "comment": "表の列を確認",
    }
    page = client.get(f"/api/documents/{doc_id}/pages/{scored[0]['page']}/elements").json()
    assert page["score"] < 100  # điểm VLM được trộn vào

    assert client.get(f"/api/documents/{doc_id}/insights").json()["detail"]["code"] == "no_insights"
    r = client.post(f"/api/documents/{doc_id}/insights", headers=H)
    assert r.status_code == 200 and r.json()["key_points"] == ["M015-2: 1,200点", "A000: 264点"]
    assert client.get(f"/api/documents/{doc_id}/insights").json()["summary"] == "歯科点数の資料。"


def test_info_text_chunks_and_roles(client, container, sample_pdf):
    _admin(client)
    doc_id = _upload(client, container, sample_pdf)
    info = client.get(f"/api/documents/{doc_id}/info").json()
    assert info["pages"] == 3 and info["language"] == "en" and info["origin"] == "upload" and info["mode"] == "full"
    assert info["size_bytes"] == len(sample_pdf)
    text = client.get(f"/api/documents/{doc_id}/text").json()
    assert [t["page"] for t in text] == [1, 2, 3] and "M015-2" in text[0]["markdown"]
    for p in container.repo.list_pages(doc_id):
        pl.submit_page(container, doc_id, p.page, "admin@example.com")
    pl.start_chunking(container, doc_id, "admin@example.com")
    run_worker(container, ["ai"], drain=True, idle_exit_s=0, poll_s=0)
    doc = container.repo.get_doc(doc_id)
    chunks = client.get(f"/api/documents/{doc_id}/pages/2/chunks").json()
    assert chunks and all(c["page_from"] <= doc.book_page(2) <= c["page_to"] for c in chunks)
    # viewer chỉ xem
    client.post("/api/users", json={"email": "v@example.com", "role": "viewer", "password": "password-123"}, headers=H)
    client.post("/api/auth/login", json={"email": "v@example.com", "password": "password-123"}, headers=H)
    assert client.get(f"/api/documents/{doc_id}/quality").status_code == 200
    assert client.post(f"/api/documents/{doc_id}/pages/1/elements/e1/accept", headers=H).status_code == 403


def test_prepare_document_auto_rereads_low_elements(container, sample_pdf):
    import app.steps.handlers  # noqa: F401

    doc = pl.create_document(
        container,
        data=sample_pdf,
        filename="s.pdf",
        name="S",
        kind="other",
        book_page_start=1,
        page_from=None,
        page_to=None,
        actor="a@example.com",
    )
    run_worker(container, ["docling", "light", "ai"], drain=True, idle_exit_s=0, poll_s=0)
    meta_key = k_page(doc.id, 1, "docling.json")
    meta = json.loads(container.blob.get(meta_key))
    meta["engine"] = "docling"
    meta["elements"] = [
        {"label": "section_header", "bbox": [0.08, 0.05, 0.3, 0.07], "text": "M015-2 CAD/CAM crown", "confidence": 0.4},
        {"label": "text", "bbox": [0.08, 0.07, 0.5, 0.11], "confidence": 0.95},
    ]
    container.blob.put(meta_key, json.dumps(meta).encode())
    container.config.overrides["llm"] = ScriptedLLM(
        lambda m, t, j: json.dumps({"markdown": "## M015-2 CAD/CAM crown", "confidence": 0.9})
    )
    svc.prepare_document(container, doc.id)
    p = container.repo.get_page(doc.id, 1)
    state = svc.load_state(container, container.repo.get_doc(doc.id), p)
    sec = next(e for e in state["elements"] if e["label"] == "section_header")
    assert sec["source"] == "vlm" and sec["reread_from"] == 0.4 and sec["status"] == "weak"
    assert _codes(sec["weak"]) == ["reread"]  # đọc lại đủ tin cậy nhưng vẫn chờ người xác nhận
    body = next(e for e in state["elements"] if e["label"] == "text")
    assert body["text"].startswith("The crown") and body["raw_text"].startswith("The crown")  # chữ lấy từ pdfium
    assert p.versions[-1].source == "element_reread" and p.versions[-1].by == "auto"
    assert pl.page_markdown(container, p).startswith("## M015-2 CAD/CAM crown\n")
    q = svc.doc_quality(container, doc.id)
    assert q and q["weak_open"] == 1 and q["counts"] == {"reread": 1}
    assert svc.open_weak_pages(container, doc.id) == {1}
