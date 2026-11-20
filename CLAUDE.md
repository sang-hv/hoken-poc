# 保険AI Bot — PoC (DEHA × Stransa)

Bot hỏi đáp về 点数 nha khoa (保険), sẽ tích hợp vào Apotool.
Kiến trúc gốc: `docs/HokenAIBot_Architecture_v3.png`. Kiến trúc khu A đã triển khai: `docs/ARCHITECTURE.md`.
Kế hoạch: `docs/PLAN.md`. **Làm xong khu A (nạp tài liệu) rồi mới làm khu B (hỏi đáp).**

Skill của repo (đọc trước khi sửa): `.claude/skills/architecture`, `.claude/skills/backend`, `.claude/skills/frontend`.

## Nguyên tắc
- **Prod**: mọi dữ liệu lưu và xử lý tại Nhật — Azure Japan East, deployment Standard (không Global / Data Zone);
  dự phòng Bedrock profile `jp.`. **Dev** được linh hoạt, miễn là dùng dịch vụ Content Understanding (Azure) và LLM.
- **Content Understanding luôn là Azure**, kể cả khi phần hạ tầng còn lại chạy Local hoặc AWS.
- **Pipeline tự chạy, chỉ dừng khi có cảnh báo** (OCR → chunk → embedding → index) — tuỳ chọn `review.mode`:
  - `warn` (mặc định): tự chạy; **dừng ở OCR レビュー** nếu còn điểm yếu ⚠, **dừng ở チャンクレビュー** nếu có chunk
    cần xem (vi phạm luật / confidence < `review.chunk_warn_below`). Khi dừng: popup cho người **review** hoặc
    **すべて承認** (duyệt hết, ghi audit, chạy luôn bước sau). Không có cảnh báo thì tự đi tiếp.
  - `auto`: tự chạy hết, cảnh báo không chặn. `manual`: luôn dừng ở hai bước review.
  Phần tử có confidence **dưới ngưỡng cài đặt** (`quality.auto_vlm_below` → AI tự đọc lại; `quality.weak_confidence`
  → gắn ⚠ cảnh báo) thì hiện cho người dùng **sửa** (→ tự chunk + index lại) hoặc **bỏ qua** (xác nhận đúng).
- Câu chatbot không trả lời được thì chuyển bộ phận CSKH (khu B).
- Repo chỉ chứa tài liệu công khai của MHLW. Không commit dữ liệu bệnh nhân, dữ liệu khách hay câu hỏi khách.
- Không commit key hay endpoint thật. Log và live log chỉ ghi mã + id/trang/mã mục/lý do, không chép nội dung tài liệu.
- Giao diện có **tiếng Anh và tiếng Nhật** — mọi chữ mới phải có ở cả `web/src/i18n/en.ts` và `ja.ts`.

## Cấu hình — 4 lớp
1. **Hạ tầng lõi** (DB, blob, queue, secret backend, JWT): biến môi trường / IaC do DevOps đặt (`.env.example`).
   Secret gốc nằm ở Key Vault / Secrets Manager; Admin UI chỉ xem.
2. **Dịch vụ AI & tích hợp** (LLM, embedding, CU, search, SSO Google/Entra): Admin chọn Local / Azure / AWS trên UI.
   Prod không có lựa chọn Local.
3. **Secret** của lớp 2: ghi vào SecretStore, DB chỉ giữ cờ "đã đặt"; ưu tiên Managed Identity / IAM role.
4. **Tuỳ chọn pipeline**: lưu DB có phiên bản; mỗi job ghi phiên bản đã dùng.

| Thành phần | Local (dev) | Azure | AWS |
|---|---|---|---|
| DB | Postgres | Cosmos DB | DynamoDB |
| Blob / Queue | thư mục / bảng Postgres | Blob / Storage Queue | S3 / SQS |
| Search hybrid | Postgres + pgvector + pg_bigm | AI Search | OpenSearch |
| LLM / embedding | OpenAI-compatible | Azure OpenAI | Bedrock |
| CU | Azure | Azure | Azure |

## Pipeline khu A
Upload → Docling (điểm confidence từng trang) → định tuyến → [CU + vision cho trang khó] → nối trang →
kiểm tra chất lượng (tự đọc lại / gắn ⚠) → cắt thô theo mã mục → LLM chunk ↔ kiểm tra luật (≤ 20 vòng) → confidence →
embedding → index. Người dùng xử lý ⚠ song song (sửa / bỏ qua), không chặn luồng.

Trang **dễ** khi: Docling `low_grade` ≥ GOOD (`low_score ≥ 0.8`), `parse_score ≥ 0.8`, không phải OCR,
không có bảng gộp ô / bảng tràn trang, không có hình lớn (sau khi bỏ logo, con dấu, chữ ký). Ngưỡng chỉnh trong Admin.

## Quy ước code
- Python ≥ 3.11, `uv`/`pip`, format + lint bằng `ruff`, test bằng `pytest`. Frontend: React + Vite + TS + Tailwind v4.
- `app/steps/*`: handler đăng ký bằng `@register`, nhận `StepCtx`, trả `list[Next]`; logic thuần ở `app/steps/rules.py`.
- `app/ports`: interface; `app/adapters/{local,azure,aws}`: triển khai; step/service không import SDK cloud.
- Ghi kết quả theo khoá `docId + page + step`; chạy lại thì ghi đè. Job idempotent theo `docId:step:page`.
- Mỗi tính năng chạy được bằng CLI: `python -m app.main serve | worker | job | upload | status | create-admin`.

## Chạy
```bash
cp .env.example .env && docker compose up -d --build     # http://localhost:8080
.venv/bin/python -m pytest -q && (cd web && npx tsc -b)
```

## Đánh giá
- OCR: `eval/eval_cer.py` (CER + kiểm tra số 点). Ground truth trong `data/gt/`.
- Retrieval: `eval/eval_retrieval.py` (Recall@K, MRR theo mã mục).
- Hỏi đáp (khu B): so câu trả lời với đáp án và căn cứ; hỏi lại 3 lần để kiểm tra tính ổn định.
