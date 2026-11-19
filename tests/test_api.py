from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.jobs import run_worker

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
