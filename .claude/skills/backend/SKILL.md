---
name: backend
description: Quy ước backend Python của khu A (FastAPI, step thuần, job idempotent, live log dạng mã, RBAC, test). Dùng khi sửa/thêm step pipeline, API, service hoặc test trong app/ và tests/.
---

# Backend khu A — quy ước

## Chạy & kiểm tra
```bash
uv venv .venv && uv pip install -p .venv -e ".[dev,azure,aws]"
.venv/bin/ruff format app tests && .venv/bin/ruff check app tests
.venv/bin/python -m pytest -q                      # memory + moto
TEST_DATABASE_URL=postgresql://hoken:hoken@localhost:5432/hoken .venv/bin/python -m pytest -q   # thêm Postgres
python -m app.main serve | worker --queues docling,ai,light | job --queues ai --idle 30
```

## Cấu trúc
- `app/domain` model Pydantic; `app/ports` interface; `app/adapters` triển khai; `app/services` nghiệp vụ;
  `app/steps` handler của pipeline; `app/api` router FastAPI; `app/main.py` CLI.
- Logic thuần (không I/O) đặt ở `app/steps/rules.py` và test trực tiếp trong `tests/test_rules.py`.

## Step
- Đăng ký bằng `@register("tên", "queue")`, nhận `StepCtx`, trả `list[Next]`.
- Đọc/ghi theo khoá `docId + page + step` (`k_page`, `k_version`), chạy lại thì **ghi đè**.
- Thiếu cấu hình dịch vụ: hoặc bỏ qua có cảnh báo (vd CU → `cu.not_configured`), hoặc `raise StepSkipped` (không retry).
- Lỗi khác → retry backoff 15s·2ⁿ đến `max_attempts`, rồi `failed` (UI có Retry).
- Vòng lặp dài phải gọi `ctx.check_cancelled()`.

## Live log & log
- `ctx.emit("mã.sự_kiện", level, **params)` — **chỉ mã + tham số** (id, trang, số đếm, điểm, lý do).
  Không bao giờ đưa nội dung tài liệu, prompt người dùng hay câu hỏi khách vào params.
- Mã mới phải có bản dịch trong `web/src/i18n/en.ts` và `ja.ts` (`events.<mã>`).

## Review: tự động trước, người xử lý ngoại lệ
- `Document.review_mode` = `review.mode` lúc upload (`pl.review_mode(doc)`; tài liệu cũ suy ra từ `auto_review`);
  `auto_review = review_mode != "manual"`. Test đặt chế độ bằng `tests.conftest.set_review_mode` / `manual_review`.
- `auto` / `warn`: `stitch` → `auto_review` (dựng phần tử, tự đọc lại dưới `quality.auto_vlm_below`, gắn điểm yếu dưới
  `quality.weak_confidence`, tự duyệt trang với người duyệt `auto`) → `chunk` → tự `index`. Người dùng sửa
  (→ `inspect.reindex_document`: chunk lại phần liên quan + index) hoặc xác nhận (`inspect.accept_element`) ở 検査.
- `warn`: `auto_review` còn điểm yếu mở (hoặc không chấm được) → `pl.hold_for_review(doc, "ocr")`; `chunk` lần đầu có
  chunk `pl.chunk_flagged` → `hold_for_review(doc, "chunk")`. `review_hold` chặn mọi đường tự đi tiếp (reindex, sửa
  chunk); chỉ `start_chunking` / `start_index` (người duyệt, `approve_all_pages` / `approve_all_chunks`) mới xoá.
- `manual` (test dùng `tests.conftest.manual_review`):
  mọi trang qua `review` → `approved`; mọi chunk `draft` → `approved`
  trước khi index. Sửa OCR sau khi đã chunk → `_invalidate_chunks` đưa tài liệu về `ocr_review`.

## API
- Lỗi nghiệp vụ: `raise PipelineError("mã", **params)` → 409 `{detail: {code, ...}}`; UI dịch theo `errors.<mã>`.
- Phân quyền: `Depends(viewer|reviewer|admin)`. Ghi thay đổi quan trọng vào audit: `c.repo.audit(...)`.
- Mọi request ghi phải có header `X-Requested-With: hoken` (chống CSRF; cookie SameSite=Lax).
- Secret không bao giờ trả về API — chỉ trả `secrets_set`.

## Test
- `tests/conftest.py` có container in-memory và `make_pdf` (PDF có lớp text).
- Adapter giả: `ScriptedLLM`, `FakeLayout`, `HashEmbedder`, `MemorySearch` — gắn qua `c.config.overrides[...]`.
