# Khu A — Hệ thống nạp tài liệu: kiến trúc đã triển khai

Bản này mô tả phần code trong repo. Sơ đồ tổng thể gốc (khu A + B): `HokenAIBot_Architecture_v3.png`.

## 1. Thành phần

```mermaid
flowchart LR
  subgraph UI["web/ (React, EN/JA)"]
    A[Admin & Reviewer UI]
  end
  subgraph API["app/api (FastAPI)"]
    R[REST + SSE live log]
  end
  subgraph W["Workers (cùng image)"]
    D[docling queue]:::heavy
    AI[ai queue]
    L[light queue]
  end
  A -- HTTPS / SSE --> R
  R -- enqueue --> Q[(Queue)]
  Q --> D & AI & L
  R & D & AI & L --> DB[(DocStore)]
  R & D & AI & L --> BL[(Blob)]
  AI --> CU[Azure Content Understanding]
  AI --> LLM[LLM / Embedding]
  AI --> S[(Search index)]
  classDef heavy fill:#fde68a
```

| Port | Local (dev / VM) | Azure | AWS |
|---|---|---|---|
| DocStore | Postgres (JSONB) | Cosmos DB | DynamoDB |
| Queue | Postgres (`SKIP LOCKED`) | Storage Queue | SQS |
| Blob | thư mục / volume | Blob Storage | S3 |
| Secret | `.env` | Key Vault → env (secretRef) | Secrets Manager → env (`secrets` của task) |
| Search | pgvector + pg_bigm (RRF) | AI Search (hybrid + semantic) | OpenSearch (kuromoji + k-NN, RRF) |
| LLM / Embedding | OpenAI-compatible | Azure OpenAI | Bedrock |
| Layout (CU) | Azure | Azure | Azure |

## 2. Pipeline và trạng thái

```mermaid
stateDiagram-v2
  [*] --> queued: upload
  queued --> docling: job docling (mỗi trang)
  docling --> routed: điểm Docling + đặc trưng bảng/hình
  routed --> cu: trang khó
  routed --> ready: trang dễ
  cu --> ready: CU + vision (hoặc bỏ qua nếu chưa cấu hình)
  ready --> review: job stitch (khi mọi trang đã ready — fan-in)
  review --> approved: người review Submit
  approved --> review: sửa lại / reopen
```

Sau khi **mọi trang approved** → `chunk` (cắt thô theo mã mục → LLM ↔ kiểm tra luật ≤ 20 vòng → confidence) →
**review chunk** (mọi chunk phải approved) → `index` (embedding + upsert).

> Trên đây là luồng **duyệt tay** (`auto_review = false`, màn 文書 cũ). Mặc định (tài liệu từ sổ tay,
> `auto_review = true`) pipeline tự chạy hết: `stitch` → `auto_review` (tự đọc lại / gắn ⚠, tự duyệt) → `chunk` →
> `index`; người dùng chỉ sửa hoặc bỏ qua chỗ có ⚠. Xem `docs/overview/01-cau-truc-he-thong.md` mục 4.

Tiêu chí **trang dễ** (điểm Docling `conv_res.confidence.pages[n]`; grade: <0.5 poor, <0.8 fair, <0.9 good, ≥0.9 excellent):
`low_score ≥ 0.8` · `parse_score ≥ 0.8` · không có `ocr_score` · không bảng gộp ô · không bảng chạm mép trên/dưới (tràn trang) ·
không hình > 5% trang (sau khi bỏ logo/con dấu/chữ ký). Ngưỡng nằm trong code (`RoutingOptions`).

## 3. Job

- Khoá `docId:step:page` → tạo có điều kiện (`DocStore.create`) nên không chạy trùng.
- Worker: nhận message → `running` → handler → `succeeded` + xếp step tiếp theo; lỗi → retry 15s·2ⁿ → `failed`.
- Live log: mỗi step ghi `JobEvent{code, params}` (không có nội dung tài liệu); API stream qua SSE theo con trỏ id
  (id có thứ tự thời gian) nên chạy được trên cả Postgres, Cosmos, DynamoDB.
- Mỗi job lưu `config_version` của tuỳ chọn pipeline để chạy lại cho kết quả giống.

## 4. Cấu hình 4 lớp

Lớp 1–3 đặt bằng biến môi trường, dev và prod giống nhau (dev `.env`, prod IaC). Admin UI chỉ xem.
1. Hạ tầng lõi — `DB_TYPE`, `BLOB_TYPE`, `QUEUE_TYPE`...
2. Dịch vụ AI & SSO — `<COMPONENT>_TYPE` + `<COMPONENT>_<FIELD>`, `AUTH_<GOOGLE|ENTRA>_*` (trường khai báo ở
   `AdapterSpec`). Prod không nhận Local, CU chỉ Azure. Màn Cài đặt hiện giá trị + báo đúng tên biến còn thiếu.
3. Secret — prod ở Key Vault / Secrets Manager, nền tảng đưa vào env; API chỉ trả cờ "đã đặt".
   Ưu tiên Managed Identity / IAM role.
4. Tuỳ chọn pipeline — mặc định trong code; Admin chỉ sửa các mục `EDITABLE` trên UI, DB có phiên bản + lịch sử.

## 5. Phân quyền

| Vai trò | Quyền |
|---|---|
| Admin | Mọi thứ + tuỳ chọn pipeline, người dùng, audit; xem cấu hình dịch vụ / SSO |
| Reviewer | Upload, review OCR/chunk, chạy lại job, tìm thử |
| Viewer | Chỉ xem |

Đăng nhập: tài khoản nội bộ (scrypt) + OIDC Google / Microsoft Entra (PKCE, kiểm tra nonce, domain cho phép).
Phiên: cookie JWT HttpOnly SameSite=Lax; request ghi bắt buộc header `X-Requested-With` (chống CSRF).

## 6. Triển khai

| Mô hình | Cách chạy |
|---|---|
| Dev / một VM | `docker compose up -d --build` — postgres (pgvector + pg_bigm), api, worker-light, worker-ai ×2, worker-parser (image Docling), web (nginx) |
| Azure | Container Apps: `web`, `api`. Container Apps Jobs (event-driven, KEDA `azure-queue` scaler) chạy `python -m app.main job --queues <q>` cho từng hàng đợi. Cosmos DB, Blob, Storage Queue, AI Search, Key Vault, Managed Identity |
| AWS | ECS Fargate: `web`, `api`; worker là ECS service scale theo độ dài SQS (hoặc RunTask chạy `job`). DynamoDB, S3, SQS, OpenSearch, Secrets Manager, Bedrock, IAM task role. CU vẫn gọi Azure |

Image: `docker/app.Dockerfile` (target `base` cho api/worker; target `docling` cho worker parser, model tải sẵn lúc build —
gồm cả model RapidOCR PP-OCRv6 dùng cho OCR tiếng Nhật),
`web/Dockerfile` (nginx, tắt buffer cho SSE), `docker/postgres/Dockerfile`.
