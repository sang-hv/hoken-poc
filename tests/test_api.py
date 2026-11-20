from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.jobs import run_worker
from tests.conftest import manual_review

H = {"X-Requested-With": "hoken"}


@pytest.fixture
def client(container):
    from app.api.server import create_app

    with TestClient(create_app()) as cl:
        yield cl


def _setup_admin(client):
    r = client.post("/api/setup", json={"email": "admin@example.com", "password": "password-123"}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_setup_login_roles_and_csrf(client, container):
    assert client.get("/api/setup/status").json()["needs_setup"] is True
    _setup_admin(client)
    assert (
        client.post("/api/setup", json={"email": "b@example.com", "password": "password-123"}, headers=H).status_code
        == 409
    )
    # Thiếu header chống CSRF → 403
    assert client.post("/api/auth/logout").status_code == 403
    r = client.post(
        "/api/users", json={"email": "v@example.com", "role": "viewer", "password": "password-123"}, headers=H
    )
    assert r.status_code == 200
    client.post("/api/auth/logout", headers=H)
    assert client.get("/api/auth/me").status_code == 401
    assert (
        client.post("/api/auth/login", json={"email": "v@example.com", "password": "wrong-pass"}, headers=H).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": "v@example.com", "password": "password-123"}, headers=H
        ).status_code
        == 200
    )
    assert client.get("/api/documents").status_code == 200
    assert client.get("/api/settings/providers").status_code == 403  # viewer không vào cài đặt


def test_provider_settings_secrets_never_returned(client, container):
    _setup_admin(client)
    cat = client.get("/api/settings/providers").json()["catalog"]
    assert {s["type"] for s in cat["cu"]} == {"azure"}
    assert {s["type"] for s in cat["llm"]} == {"local", "azure", "aws"}
    body = {
        "type": "azure",
        "config": {"endpoint": "https://x.openai.azure.com", "deployment": "gpt", "auth": "key"},
        "secrets": {"api_key": "SUPER-SECRET"},
    }
    r = client.put("/api/settings/providers/llm", json=body, headers=H)
    assert r.status_code == 200, r.text
    assert "SUPER-SECRET" not in r.text
    comp = r.json()["components"]["llm"]
    assert comp["secrets_set"] == ["api_key"]
    assert container.secrets.get("hoken-llm-azure-api-key") == "SUPER-SECRET"
    # Cập nhật không gửi lại secret → giữ secret cũ
    body["secrets"] = {}
    body["config"]["deployment"] = "gpt2"
    r = client.put("/api/settings/providers/llm", json=body, headers=H)
    assert r.json()["components"]["llm"]["secrets_set"] == ["api_key"]
    # Thiếu trường bắt buộc → 400
    r = client.put("/api/settings/providers/cu", json={"type": "azure", "config": {}}, headers=H)
    assert r.status_code == 400


def test_prod_hides_local(container):
    from app.services.config_service import ConfigService

    cs = ConfigService(container.repo, container.secrets, "prod")
    cat = cs.catalog()
    assert all(s["type"] != "local" for specs in cat.values() for s in specs)


def test_upload_review_flow_via_api(client, container, sample_pdf):
    import app.steps.handlers  # noqa: F401

    _setup_admin(client)
    manual_review(container)  # luồng duyệt tay (review.auto_review = false)
    r = client.post(
        "/api/documents",
        files={"file": ("s.pdf", sample_pdf, "application/pdf")},
        data={"name": "Sample", "kind": "akahon", "book_page_start": "536"},
        headers=H,
    )
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    run_worker(container, ["docling", "light", "ai"], drain=True, idle_exit_s=0, poll_s=0)
    pages = client.get(f"/api/documents/{doc_id}/pages").json()
    assert len(pages) == 3 and all(p["status"] == "review" for p in pages)
    detail = client.get(f"/api/documents/{doc_id}/pages/1").json()
    assert "M015-2" in detail["markdown"] and "docling" in detail["sources"]
    assert client.get(f"/api/documents/{doc_id}/pages/1/image").headers["content-type"] == "image/png"
    # Chưa duyệt hết trang → không chunk được
    r = client.post(f"/api/documents/{doc_id}/actions/start_chunking", headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "pages_not_approved"
    for p in pages:
        assert client.post(f"/api/documents/{doc_id}/pages/{p['page']}/submit", json={}, headers=H).status_code == 200
    assert client.get(f"/api/documents/{doc_id}").json()["status"] == "ready_for_chunking"
    assert client.post(f"/api/documents/{doc_id}/actions/start_chunking", headers=H).status_code == 200
    run_worker(container, ["ai"], drain=True, idle_exit_s=0, poll_s=0)
    chunks = client.get(f"/api/documents/{doc_id}/chunks").json()
    assert chunks
    # Gộp 2 chunk đầu rồi tách lại
    merged = client.post(
        f"/api/documents/{doc_id}/chunks/merge", json={"ids": [chunks[0]["id"], chunks[1]["id"]]}, headers=H
    ).json()
    parts = client.post(f"/api/documents/{doc_id}/chunks/{merged['id']}/split", json={"offset": 10}, headers=H).json()
    assert len(parts) == 2
    jobs = client.get(f"/api/jobs?doc_id={doc_id}").json()
    assert {j["step"] for j in jobs} >= {"docling", "route", "stitch", "chunk"}
    events = client.get(f"/api/documents/{doc_id}/events").json()
    assert any(e["code"] == "stitch.done" for e in events)
    dash = client.get("/api/dashboard").json()
    assert dash["documents"] == 1


def test_rename_and_paged_lists(client, container, sample_pdf):
    import app.steps.handlers  # noqa: F401

    _setup_admin(client)
    doc_id = client.post(
        "/api/documents",
        files={"file": ("s.pdf", sample_pdf, "application/pdf")},
        data={"name": "Sample", "kind": "akahon"},
        headers=H,
    ).json()["id"]
    run_worker(container, ["docling", "light", "ai"], drain=True, idle_exit_s=0, poll_s=0)

    # Đổi tên: tên rỗng giữ nguyên, tên mới ghi audit (chỉ id, không chép tên)
    assert client.patch(f"/api/documents/{doc_id}", json={"name": "  "}, headers=H).json()["name"] == "Sample"
    assert client.patch(f"/api/documents/{doc_id}", json={"name": " Renamed "}, headers=H).json()["name"] == "Renamed"
    audit = client.get("/api/audit?q=doc.rename&paged=true").json()
    assert audit["total"] == 1 and audit["items"][0]["target"] == doc_id
    assert "Renamed" not in str(audit["items"][0]["detail"])

    # Jobs: mặc định vẫn trả mảng; paged trả {items, total}; q lọc theo tên tài liệu
    assert isinstance(client.get("/api/jobs").json(), list)
    page = client.get("/api/jobs?paged=true&limit=2&offset=1").json()
    total = page["total"]
    assert total >= 4 and len(page["items"]) == 2
    assert client.get("/api/jobs?paged=true&q=renam").json()["total"] == total
    assert client.get("/api/jobs?paged=true&q=nope").json() == {"items": [], "total": 0}


def test_page_low_confidence_and_raw_json(client, container, sample_pdf):
    import json

    import app.steps.handlers  # noqa: F401
    from app.steps.common import k_page

    _setup_admin(client)
    doc_id = client.post(
        "/api/documents",
        files={"file": ("s.pdf", sample_pdf, "application/pdf")},
        data={"name": "Sample", "kind": "akahon"},
        headers=H,
    ).json()["id"]
    run_worker(container, ["docling", "light", "ai"], drain=True, idle_exit_s=0, poll_s=0)
    cu = {
        "result": {
            "contents": [
                {
                    "markdown": "x",
                    "pages": [
                        {
                            "width": 8.0,
                            "height": 10.0,
                            "words": [{"content": "点", "confidence": 0.5, "source": "D(1,0,0,4,0,4,5,0,5)"}],
                        }
                    ],
                }
            ]
        }
    }
    container.blob.put(k_page(doc_id, 1, "cu.json"), json.dumps(cu).encode(), "application/json")

    page = client.get(f"/api/documents/{doc_id}/pages/1").json()
    low = page["low_confidence"]
    assert low["threshold"] == 0.8
    assert low["boxes"] == [
        {"source": "cu", "label": "word", "text": "点", "confidence": 0.5, "bbox": [0.0, 0.0, 0.5, 0.5], "span": None}
    ]
    assert client.get(f"/api/documents/{doc_id}/pages/1/raw/cu").json() == cu
    assert "elements" in client.get(f"/api/documents/{doc_id}/pages/1/raw/docling").json()
    assert client.get(f"/api/documents/{doc_id}/pages/1/raw/secrets").status_code == 404
    assert client.get(f"/api/documents/{doc_id}/pages/2/raw/cu").status_code == 404


def test_document_upload_runs_automatically_by_default(client, container, sample_pdf):
    """Mặc định (review.auto_review = true): upload ở màn 文書 cũng tự chạy hết tới chunk, tự duyệt bởi "auto"."""
    import app.steps.handlers  # noqa: F401

    _setup_admin(client)
    r = client.post("/api/documents", files={"file": ("s.pdf", sample_pdf, "application/pdf")}, headers=H)
    doc_id = r.json()["id"]
    assert r.json()["auto_review"] is True
    run_worker(container, ["docling", "light", "ai"], drain=True, idle_exit_s=0, poll_s=0)
    pages = client.get(f"/api/documents/{doc_id}/pages").json()
    assert all(p["status"] == "approved" and p["reviewed_by"] == "auto" for p in pages)
    chunks = client.get(f"/api/documents/{doc_id}/chunks").json()
    assert chunks and all(ch["status"] != "draft" for ch in chunks)
