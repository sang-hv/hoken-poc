# 保険AI Bot — PoC

Khu A: hệ thống nạp tài liệu (upload → Docling → định tuyến → Content Understanding → nối trang → **review OCR** →
agentic chunking → **review chunk** → embedding → index), có live log, phân quyền, giao diện tiếng Anh / tiếng Nhật,
chạy được trên một VM, Azure hoặc AWS qua adapter.

- Kiến trúc: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · Quy ước: [`CLAUDE.md`](CLAUDE.md)

## Chạy nhanh (Docker)

```bash
cp .env.example .env        # đổi SECRET_MASTER_KEY và JWT_SECRET
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

Docling (nặng) chỉ có trong image `worker-docling`. Chạy ngoài Docker mà không cài `.[docling]` thì trang được trích
bằng pdfium và luôn được định tuyến sang Content Understanding (lý do `no_docling`).
