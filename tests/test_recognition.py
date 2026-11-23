"""Tổng kết nhận diện của tài liệu (良好 / 要確認 / 未認識) — docs/STATUS.md §C."""

from __future__ import annotations

from app.services import inspect as svc
from app.steps import rules
from tests.test_inspect import H, _admin, _upload, client  # noqa: F401 — fixture client dùng lại


def _f(*codes):
    return [{"code": c, "severity": "warn"} for c in codes]


def test_flags_bucket_worst_wins():
    assert rules.flags_bucket([]) == "good"
    assert rules.flags_bucket(_f("low_confidence")) == "weak"
    assert rules.flags_bucket(_f("table_suspect", "reread", "ocr_weak")) == "weak"
    for code in ("missing_text", "blank_page", "picture_no_desc"):
        assert rules.flags_bucket(_f(code)) == "unread"
    assert rules.flags_bucket(_f("low_confidence", "missing_text")) == "unread"


def test_element_bucket_handled_and_header_footer():
    assert rules.element_bucket({"label": "text", "status": "ok", "weak": []}) == "good"
    assert rules.element_bucket({"label": "text", "status": "weak", "weak": _f("missing_text")}) == "unread"
    # người đã xử lý → fixed, dù vẫn còn điểm yếu trong danh sách
    assert rules.element_bucket({"label": "table", "status": "accepted", "weak": _f("table_suspect")}) == "fixed"
    assert rules.element_bucket({"label": "text", "status": "fixed", "weak": _f("missing_text")}) == "fixed"
    assert rules.element_bucket({"label": "page_header", "status": "ok", "weak": []}) is None


def test_summary_endpoint_initial_kept_after_edit(client, container, sample_pdf):  # noqa: F811
    _admin(client)
    doc_id = _upload(client, container, sample_pdf)
    r = client.get(f"/api/documents/{doc_id}/recognition")
    assert r.status_code == 200, r.text
    s = r.json()
    n = s["elements"]
    assert n > 0 and s["unit"] == "element" and s["estimated"] == 0
    assert sum(s["current"].values()) == n and sum(s["initial"].values()) == n
    assert set(s["current"]) == set(rules.BUCKETS) and set(s["initial"]) == {"good", "weak", "unread"}
    assert sum(p["elements"] for p in s["pages"]) == n and s["pages_failed"] == []
    before = dict(s["initial"])

    # Sửa một phần tử → hiện tại: fixed tăng 1; lúc máy đọc: không đổi
    els = client.get(f"/api/documents/{doc_id}/pages/1/elements").json()["elements"]
    target = next(e for e in els if e["label"] not in rules.HEADER_FOOTER)
    client.put(f"/api/documents/{doc_id}/pages/1/elements/{target['id']}", json={"text": "M015-2"}, headers=H)
    after = client.get(f"/api/documents/{doc_id}/recognition").json()
    assert after["initial"] == before
    assert after["current"]["fixed"] == s["current"]["fixed"] + 1

    assert client.get("/api/documents/nope/recognition").status_code == 404


def test_summary_estimates_old_state_without_initial(client, container, sample_pdf):  # noqa: F811
    _admin(client)
    doc_id = _upload(client, container, sample_pdf)
    doc, p = container.repo.get_doc(doc_id), container.repo.get_page(doc_id, 1)
    state = svc.load_state(container, doc, p)
    for e in state["elements"]:
        e.pop("initial", None)  # dữ liệu trước khi có trường initial
    svc._save_state(container, doc_id, 1, state)
    s = svc.recognition_summary(container, doc_id)
    assert s["estimated"] == s["pages"][0]["elements"] > 0
