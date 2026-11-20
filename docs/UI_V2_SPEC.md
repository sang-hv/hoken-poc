# UI v2 — trang demo cho khách (PoC)

Yêu cầu gốc: sếp gửi (6 ảnh giao diện, tiếng Việt). Giao diện **tiếng Nhật là mặc định**, vẫn có tiếng Anh
(`web/src/i18n/v2/*.ts`). Mọi chữ hiển thị qua `t()`.

## Luồng

Menu: **運用** ダッシュボード · 文書 — **テスト** チャット (chat với bot trên toàn bộ tài liệu đã index, logic cũ
`/api/chat/test`) — **管理** 設定 · ユーザー · 監査ログ. Không có ライブラリ / ノートブック, màn ジョブ, màn 検索.

1. **文書 (Danh sách tài liệu)**: tải PDF / ảnh (PNG, JPEG → PDF 1 trang) lên → **pipeline tự chạy hết**
   (Docling → định tuyến → CU/VLM → nối trang → *tự duyệt* → chunk → *tự duyệt* → embed + index) theo
   `review.auto_review` (mặc định bật). Index xong là chat được ngay ở màn チャット.
2. **Chi tiết tài liệu** `/documents/:docId` — 6 tab (mở 原本 nếu đã index xong, còn lại mở パイプライン):
   - **パイプライン**: tiến độ 8 bước, nút thao tác (đổi tên, chạy lại trang lỗi, duyệt tay khi tắt tự chạy),
     điểm chất lượng + 「要確認 N件」, lưới trang + live log, bảng định tuyến. Index xong → nút 「チャットで試す」.
   - **原本 (Bản gốc)**: thumbnail trái, ảnh trang giữa (zoom), panel thông tin phải.
   - **テキスト (Văn bản)**: Markdown sau xử lý, từng trang có nhãn `p.N`.
   - **チャンク (Chunk — cấp tài liệu)** `?tab=chunks&chunk=<id>`: toàn bộ chunk theo thứ tự; chunk có thể trải
     nhiều trang (cắt theo mã mục trên văn bản đã nối trang) → hiện dải trang PDF + trang sách, 「Nページにまたがる」,
     ⚠ khi trang của chunk còn điểm yếu. Sửa / tách tại con trỏ / gộp với chunk sau; tài liệu tự chạy → lưu xong tự
     duyệt + index lại. Panel チャンク trong 検査 giữ để xem chunk liên quan trang đang xem (nhãn 「このページから」
     「前ページから続く」「次ページへ続く」, nút mở trong tab này).
   - **インサイト (Nhận định)**: tóm tắt + ý chính do LLM tạo (nút tạo lại).
   - **検査 (Kiểm tra)**: thanh chất lượng (điểm + hạng, trang kém nhất, đếm điểm yếu theo loại, nút
     「弱点をAIで修正」「AIで採点」), thumbnail trái, ảnh trang với khung phần tử đánh số theo thứ tự đọc
     (màu theo loại), panel phải 4 tab: **要素** (Tất cả / Điểm yếu / Đã sửa; hover = highlight khung; click =
     chi tiết: ảnh cắt, Markdown đọc được, sửa tay, đọc lại bằng AI, JSON) · **チャンク** (chunk của trang) ·
     **弱点** (danh sách điểm yếu toàn tài liệu) · **修正履歴** (lịch sử sửa).
   Màn review cũ (`/documents/:docId/pages/:n`, `/chunks`) vẫn mở được từ lưới trang / menu その他.

## Human in the loop (tạm — chờ sếp gửi bản chính)

Pipeline tự chạy hết để khách chat được ngay; **không bỏ** việc người kiểm tra mà chuyển thành *xử lý ngoại lệ*:
- Mỗi phần tử có `status`: `ok` · `weak` (cần người xem) · `fixed` (đã sửa tay / AI) · `accepted` (người xác nhận
  đúng). Điểm yếu chỉ hết khi người **sửa** hoặc **xác nhận**.
- Phần tử điểm thấp được **tự gọi VLM** đọc lại trước (theo `quality.auto_vlm_below`); vẫn thấp thì đánh dấu `weak`.
- 「要確認 N件」 trên tab パイプライン và 検査.
- Tài liệu upload khi `review.auto_review = true`: trang/chunk được duyệt tự động với người duyệt `auto`; sửa
  phần tử → chunk + index lại. Tắt tuỳ chọn thì quay lại duyệt tay.

Mã điểm yếu (`code`): `low_confidence` · `picture_no_desc` (hình chưa có mô tả) · `missing_text` (vùng có chữ nhưng
đọc ra rỗng/quá ngắn) · `table_suspect` (bảng gộp ô / tràn trang / số cột lệch) · `reread` (đã phải đọc lại bằng
VLM) · `blank_page` · `ocr_weak` (trang scan, điểm OCR thấp).

## API — Tài liệu

`POST /api/documents multipart(file, name?, kind?, …)` nhận PDF / PNG / JPEG (`unsupported_file` với loại khác).

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
