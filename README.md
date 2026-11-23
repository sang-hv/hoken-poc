# 保険AI Bot — PoC

Khu A: hệ thống nạp tài liệu (upload → parser (Docling / PaddleOCR) → định tuyến → Content Understanding → nối trang → **review OCR** →
agentic chunking → **review chunk** → embedding → index), có live log, phân quyền, giao diện tiếng Anh / tiếng Nhật,
chạy được trên một VM, Azure hoặc AWS qua adapter.

- Kiến trúc: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · Quy ước: [`CLAUDE.md`](CLAUDE.md)

## Chạy nhanh (Docker)

```bash
cp .env.example .env        # đổi JWT_SECRET, điền LLM_* / EMBEDDING_* / CU_* / SEARCH_*
docker compose up -d --build
```

Mở http://localhost:8080 → màn **Setup** tạo admin → **Cài đặt → AI services** chọn Local / Azure / AWS cho LLM,
embedding, Content Understanding (Azure) và search → **Tài liệu → Upload PDF**.

## Phát triển

```bash
uv venv .venv && uv pip install -p .venv -e ".[dev,azure,aws]"
.venv/bin/python -m pytest -q
.venv/bin/python -m app.main serve            # API :8000
.venv/bin/python -m app.main worker           # worker cho cả 3 hàng đợi
cd web && npm ci && npm run dev               # UI :5173 (proxy /api → :8000)
```

**Parser (標準解析)** chọn bằng `PARSER_TYPE` trong `.env`: `docling` hoặc `paddleocr` (PP-StructureV3). Cả hai trả cùng
định dạng (Markdown, điểm, bảng / hình, phần tử có confidence) nên các bước sau không đổi.
- Docker: `docker compose up -d --build` build image `worker-parser` đúng theo `PARSER_TYPE` (model tải sẵn lúc build).
- Ngoài Docker: `scripts/dev/setup_parser.sh` tạo `.venv-parser` (Python 3.12) rồi `MOCK_AI=0 scripts/demo/up.sh` chạy
  worker parser bằng venv đó (dịch vụ AI thật theo `.env`; bỏ `MOCK_AI=0` để dùng mock).
- Worker không có thư viện parser thì trích bằng lớp text pdfium, live log cảnh báo `parser.unavailable` và trang luôn
  được định tuyến sang 精密解析 (lý do `no_docling`).
