# UI v2 — trang demo cho khách (PoC)

Yêu cầu gốc: sếp gửi (6 ảnh giao diện, tiếng Việt). Giao diện **tiếng Nhật là mặc định**, vẫn có tiếng Anh
(`web/src/i18n/v2/*.ts`). Mọi chữ hiển thị qua `t()`.

## Luồng

1. **ライブラリ (Thư viện)**: danh sách ノートブック (sổ tay). Tạo / đổi tên / xoá sổ tay.
2. **ノートブック (Sổ tay)** — 3 cột (ảnh 1):
   - **ソース (Nguồn)**: tải PDF / ảnh (PNG, JPEG) lên → **pipeline tự chạy hết** (Docling → định tuyến → CU/VLM →
     nối trang → *tự duyệt* → chunk → *tự duyệt* → embed + index). Mỗi nguồn hiện tiến độ / bước đang chạy /
     điểm chất lượng / số điểm yếu chưa xử lý; công tắc dùng nguồn này khi chat. Bấm nguồn → màn chi tiết.
   - **メモ (Ghi chú)**: khách bổ sung thông tin; ghi chú cũng là nguồn cho chat.
   - **チャット (Trò chuyện)**: **Agentic RAG** trên các nguồn đang bật + ghi chú. Chọn ngôn ngữ trả lời
     (自動/日本語/English/Tiếng Việt) và chế độ (標準 / じっくり回答 = nhiều bước tìm hơn). Câu trả lời có trích dẫn
     [n] (tài liệu + trang); trích từ trang còn điểm yếu chưa xử lý thì gắn ⚠.
3. **Chi tiết nguồn** — 4 tab (ảnh 2–7):
   - **原本 (Bản gốc)**: thumbnail trái, ảnh trang giữa (zoom), panel thông tin phải.
   - **テキスト (Văn bản)**: Markdown sau xử lý, từng trang có nhãn `p.N`.
   - **インサイト (Nhận định)**: tóm tắt + ý chính do LLM tạo (nút tạo lại).
   - **検査 (Kiểm tra)**: thanh chất lượng (điểm + hạng, trang kém nhất, đếm điểm yếu theo loại, nút
     「弱点をAIで修正」「AIで採点」), thumbnail trái, ảnh trang với khung phần tử đánh số theo thứ tự đọc
     (màu theo loại), panel phải 4 tab: **要素** (Tất cả / Điểm yếu / Đã sửa; hover = highlight khung; click =
     chi tiết: ảnh cắt, Markdown đọc được, sửa tay, đọc lại bằng AI, JSON) · **チャンク** (chunk của trang) ·
     **弱点** (danh sách điểm yếu toàn tài liệu) · **修正履歴** (lịch sử sửa).

## Human in the loop (tạm — chờ sếp gửi bản chính)

Pipeline tự chạy hết để khách chat được ngay; **không bỏ** việc người kiểm tra mà chuyển thành *xử lý ngoại lệ*:
- Mỗi phần tử có `status`: `ok` · `weak` (cần người xem) · `fixed` (đã sửa tay / AI) · `accepted` (người xác nhận
  đúng). Điểm yếu chỉ hết khi người **sửa** hoặc **xác nhận**.
- Phần tử điểm thấp được **tự gọi VLM** đọc lại trước (theo `quality.auto_vlm_below`); vẫn thấp thì đánh dấu `weak`.
- Banner trên tab 検査 và trên thẻ nguồn: 「要確認 N件」. Câu trả lời chat trích trang còn điểm yếu → ⚠ + link.
- Tài liệu tạo từ sổ tay có `auto_review = true`: trang/chunk được duyệt tự động với người duyệt `auto`.
  Tài liệu upload ở màn 文書 cũ vẫn theo quy trình duyệt tay như trước.

Mã điểm yếu (`code`): `low_confidence` · `picture_no_desc` (hình chưa có mô tả) · `missing_text` (vùng có chữ nhưng
đọc ra rỗng/quá ngắn) · `table_suspect` (bảng gộp ô / tràn trang / số cột lệch) · `reread` (đã phải đọc lại bằng
VLM) · `blank_page` · `ocr_weak` (trang scan, điểm OCR thấp).

## API — Sổ tay (backend A1: `app/api/routers/notebooks.py`)

```
GET    /api/notebooks                              → NotebookSummary[]
POST   /api/notebooks {name}                       → NotebookSummary
GET    /api/notebooks/{nb}                         → NotebookDetail
PATCH  /api/notebooks/{nb} {name}                  → NotebookSummary
DELETE /api/notebooks/{nb}                         → {ok}
POST   /api/notebooks/{nb}/sources  multipart(file, name?) → NotebookSource   (PDF/PNG/JPEG; ảnh → PDF 1 trang)
PATCH  /api/notebooks/{nb}/sources/{doc} {enabled} → NotebookSource
DELETE /api/notebooks/{nb}/sources/{doc}           → {ok}   (xoá luôn tài liệu)
POST   /api/notebooks/{nb}/notes {title?, text}    → Note
PATCH  /api/notebooks/{nb}/notes/{id} {title?, text?} → Note
DELETE /api/notebooks/{nb}/notes/{id}              → {ok}
POST   /api/notebooks/{nb}/chat {q, history[], mode: "auto"|"deep", lang: "auto"|"ja"|"en"|"vi"} → ChatAnswer
```
Quyền: xem = viewer, sửa/upload/chat = reviewer.

## API — Kiểm tra (backend A2: `app/api/routers/inspect.py`)

```
GET  /api/documents/{doc}/info                     → DocInfo
GET  /api/documents/{doc}/text                     → PageText[]
GET  /api/documents/{doc}/insights                 → Insights | 404 {code:"no_insights"}
POST /api/documents/{doc}/insights                 → Insights   (tạo/tạo lại bằng LLM)
GET  /api/documents/{doc}/quality                  → DocQuality
GET  /api/documents/{doc}/weak                     → WeakItem[]
POST /api/documents/{doc}/fix-weak                 → {queued}   (AI đọc lại mọi phần tử weak)
POST /api/documents/{doc}/score {pages?: int[]}    → {scored: PageScore[]}  (VLM chấm tối đa 5 trang điểm thấp nhất)
GET  /api/documents/{doc}/pages/{n}/elements       → PageElements
GET  /api/documents/{doc}/pages/{n}/elements/{eid}/image  → PNG (ảnh cắt)
GET  /api/documents/{doc}/pages/{n}/elements/{eid}/raw    → JSON thô của phần tử
PUT  /api/documents/{doc}/pages/{n}/elements/{eid} {text} → Element   (sửa tay → status fixed, source manual)
POST /api/documents/{doc}/pages/{n}/elements/{eid}/reread {prompt?} → Element (VLM trên ảnh cắt)
POST /api/documents/{doc}/pages/{n}/elements/{eid}/accept → Element (người xác nhận đúng)
GET  /api/documents/{doc}/pages/{n}/chunks         → Chunk[] (chunk phủ trang n)
GET  /api/documents/{doc}/pages/{n}/history        → HistoryItem[]
```
Ảnh trang dùng endpoint sẵn có `GET /api/documents/{doc}/pages/{n}/image`.

## Kiểu dữ liệu (TypeScript ở `web/src/lib/v2types.ts`, Python tự định nghĩa tương ứng)

Xem `web/src/lib/v2types.ts` — đó là hợp đồng chung, backend trả đúng các field này (snake_case).
