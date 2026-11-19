---
name: architecture
description: Kiến trúc khu A (nạp tài liệu) của 保険AI Bot — port/adapter cho Local/Azure/AWS, 4 lớp cấu hình, mô hình chạy job (VM, Container Apps Jobs, ECS). Dùng khi thêm dịch vụ/adapter mới, đổi cách deploy, hoặc quyết định một cấu hình nên nằm ở đâu.
---

# Kiến trúc khu A

Đọc kèm: `docs/ARCHITECTURE.md` (sơ đồ + triển khai), `docs/HokenAIBot_Architecture_v3.png` (sơ đồ gốc).

## Nguyên tắc
1. **Step và service chỉ phụ thuộc vào `app/ports`** — không import SDK cloud ngoài `app/adapters/{local,azure,aws}`.
2. **Mọi adapter có test hợp đồng** trong `tests/test_contracts.py` (cùng một bộ test cho memory / Postgres / moto / Azurite).
   Thêm adapter mới = thêm một `pytest.param` vào đúng hàm `_stores/_queues/_blobs/_secrets/_searches`.
3. **Content Understanding luôn là Azure**, kể cả khi hạ tầng còn lại là AWS hoặc Local.
4. Prod (`APP_ENV=prod`) không có lựa chọn Local trên UI (`specs_for` lọc bỏ).

## 4 lớp cấu hình — đặt cấu hình mới ở đâu?
| Lớp | Ví dụ | Nơi lưu | Ai đổi |
|---|---|---|---|
| 1 Hạ tầng lõi | DB, Blob, Queue, secret backend, JWT secret | env / IaC (`app/core/settings.py`) | DevOps, Admin UI chỉ xem |
| 2 Dịch vụ AI & tích hợp | LLM, embedding, CU, search, SSO | DB `settings/providers` + `AdapterSpec` trong `app/adapters/registry.py` | Admin trên UI |
| 3 Secret | API key, client secret | SecretStore (Key Vault / Secrets Manager / local AES-GCM), DB chỉ giữ cờ | Admin, chỉ ghi |
| 4 Tuỳ chọn pipeline | ngưỡng định tuyến, prompt, số vòng | DB có phiên bản (`app/domain/options.py`) | Admin |

Quy tắc: thứ gì đổi giữa chừng làm mất dữ liệu (DB, blob, queue) → lớp 1. Thứ gì chỉ là dịch vụ được gọi → lớp 2.
Search ở lớp 2 vì dựng lại được từ chunk đã duyệt.

## Bảng adapter
| Port | Local | Azure | AWS |
|---|---|---|---|
| DocStore | `local/pg_store.py` | `azure/cosmos.py` | `aws/dynamodb.py` |
| Queue | `local/pg_queue.py` | `azure/storage_queue.py` | `aws/sqs.py` |
| BlobStore | `local/fs_blob.py` | `azure/blob.py` | `aws/s3.py` |
| SecretStore | `local/secret_store.py` | `azure/keyvault.py` | `aws/secrets_manager.py` |
| SearchIndex | `local/pg_search.py` | `azure/ai_search.py` | `aws/opensearch.py` |
| LLM / Embedder | `local/openai_compat.py` | `azure/openai.py` | `aws/bedrock.py` |
| LayoutAnalyzer | — | `azure/cu.py` | — (dùng Azure) |

## Thêm adapter lớp 2 (vd. search mới)
1. Tạo class có `from_config(cfg, secrets)` + `health()` + các method của port.
2. Khai báo `AdapterSpec(component, type, service, "module:Class", fields)` trong `CATALOG`.
   Trường `kind="secret"` tự đi vào SecretStore; `show_if` để ẩn/hiện theo lựa chọn khác.
3. UI tự sinh form; thêm nhãn trường vào `web/src/i18n/{en,ja}.ts` (`settings.fields.*`).
4. Thêm test (REST giả trong `tests/test_rest_adapters.py` hoặc hợp đồng).

## Mô hình chạy job
- Ba hàng đợi: `docling` (nặng, image riêng), `ai` (gọi CU/LLM/embedding), `light` (định tuyến, nối trang).
- `python -m app.main worker --queues X` — chạy liên tục (compose / VM / ECS service).
- `python -m app.main job --queues X --idle 30` — xử lý đến khi rỗng rồi thoát (Azure Container Apps Job với KEDA scaler theo độ dài queue; ECS RunTask).
- Job idempotent theo khoá `docId:step:page`; fan-in (đủ trang mới nối) dùng `enqueue(force=True)` + `create` có điều kiện.
