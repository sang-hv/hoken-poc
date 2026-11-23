# Định nghĩa trạng thái — khu A

Nguồn duy nhất cho mọi trạng thái hiển thị trên UI. Code: `app/domain/models.py` (enum), `app/steps/rules.py`
(điểm yếu, điểm, nhóm nhận diện), `app/domain/options.py` (ngưỡng — chỉnh trong 設定 > パイプライン).
Ngưỡng ghi dưới đây là mặc định.

## A. Trạng thái tài liệu (pipeline) — `DocStatus`

| Status | 日本語 | Nghĩa | Sang bước sau khi | Bước trên stepper |
|---|---|---|---|---|
| `processing` | 処理中 | Docling → định tuyến → CU chạy theo từng trang | mọi trang xong (hoặc lỗi) | Docling · 振り分け · CU |
| `stitching` | ページ結合中 | nối trang, bỏ header/footer, nối bảng tràn trang | nối xong | ページ結合 |
| `ocr_review` | OCR レビュー | chờ người duyệt trang (xem `review.mode`) | mọi trang 承認 hoặc すべて承認 | OCR レビュー |
| `ready_for_chunking` | チャンク化待ち | mọi trang đã duyệt; *trạng thái chờ*, không phải bước riêng | bắt đầu chunk (auto / warn: tự động) | (giữa OCR レビュー và チャンク化) |
| `chunking` | チャンク化中 | cắt thô theo mã mục → LLM chunk ↔ kiểm luật (≤ 20 vòng) → confidence | chunk xong | チャンク化 |
| `chunk_review` | チャンクレビュー | chờ người duyệt chunk | mọi chunk 承認 hoặc すべて承認 | チャンクレビュー |
| `indexing` | インデックス作成中 | embedding + ghi vào search | xong | 埋め込み・インデックス |
| `indexed` | インデックス済み | chatbot dùng được (nếu tài liệu đang 有効) | — | (xong) |
| `failed` | 失敗 | có bước lỗi không tự thử lại được | 「失敗ページを再実行」 | bước đang chạy = 失敗 |

**Chế độ duyệt `review.mode`** (ghi vào tài liệu lúc upload):
- `warn` (mặc định): tự chạy; dừng ở OCR レビュー nếu còn phần tử ⚠ (§C), dừng ở チャンクレビュー nếu có chunk cần xem (§E).
- `auto`: tự chạy hết, ⚠ chỉ là cảnh báo. `manual`: luôn dừng ở cả hai bước review.

**Trạng thái của một bước trên stepper:** 待機 (chưa tới) · 処理中 · 対応待ち (dừng chờ người) · 完了 · 失敗.

## B. Trạng thái trang — `PageStatus`

| Status | Nghĩa |
|---|---|
| `queued` | chờ Docling |
| `docling` | đang chạy Docling (có điểm `parse_score`, `low_score`… sau bước này) |
| `routed` | đã định tuyến: **dễ** → dùng kết quả Docling; **khó** → gửi CU |
| `cu` | đang chạy Content Understanding |
| `ready` | đã có nội dung, chờ nối trang |
| `review` | chờ người duyệt (OCR レビュー) |
| `approved` | đã duyệt (người, すべて承認, hoặc tự duyệt khi `auto` / `warn` không có ⚠) |
| `failed` | lỗi ở Docling / CU; không có phần tử → tính là trang **未認識** trong tổng kết |

**Trang dễ** khi đủ cả: Docling `low_score ≥ 0.8` (hạng ≥ GOOD), `parse_score ≥ 0.8`, không phải trang OCR, không
có bảng gộp ô / tràn trang, không có hình lớn (sau khi bỏ logo, con dấu, chữ ký).

**Hạng Docling (「Docling 判定」)** — điểm *đầu vào* do Docling chấm, chỉ dùng để định tuyến:
`POOR` < 0.5 ≤ `FAIR` < 0.8 ≤ `GOOD` < 0.9 ≤ `EXCELLENT`. Khác hoàn toàn với 品質 (§D).

## C. Nhận diện phần tử (tab 検査)

Phần tử = một đoạn / tiêu đề / bảng / hình / chú thích… theo thứ tự đọc. Header, footer, số trang **không** tính
(bị bỏ khi nối trang).

### Điểm yếu (⚠) — gắn tự động sau OCR
| Mã | Mức | Điều kiện | Nhóm |
|---|---|---|---|
| `missing_text` | error | vùng có chữ (≥ 4 ký tự trong lớp text / OCR thô) nhưng nội dung đọc ra < 30% độ dài đó | 未認識 |
| `blank_page` | error | cả trang đọc ra < 5 ký tự có nghĩa | 未認識 |
| `picture_no_desc` | warn | hình chưa có mô tả (bật `picture_needs_description`) | 未認識 |
| `low_confidence` | warn / error | confidence < 0.8 (`weak_confidence`); < 0.6 (`auto_vlm_below`) là error và được AI tự đọc lại | 要確認 |
| `ocr_weak` | warn | trang scan có điểm OCR < 0.8 | 要確認 |
| `table_suspect` | warn | bảng nghi vỡ: không ra dạng bảng, số cột lệch, gộp ô, hoặc tràn sang trang khác | 要確認 |
| `reread` | warn | đã phải cho AI đọc lại (kèm confidence trước đó) | 要確認 |

### Trạng thái phần tử
| Status | Nghĩa |
|---|---|
| `ok` | không có điểm yếu |
| `weak` | còn ít nhất một điểm yếu chưa xử lý |
| `fixed` (修正済み) | người sửa tay, hoặc người bấm AI đọc lại (「AIで再読込」 / 「弱点をAIで修正」) |
| `accepted` (確認済み) | người xác nhận nội dung đúng (「問題なし」) |

AI **tự** đọc lại trong pipeline (confidence < 0.6) không đổi status: phần tử mang thêm `reread` và vẫn là `weak`
để người kiểm tra.

### Nhóm nhận diện (tổng kết một tài liệu)
Mỗi phần tử thuộc đúng một nhóm; nhiều điểm yếu thì lấy nhóm nặng nhất (未認識 > 要確認 > 良好).

| Nhóm | Điều kiện |
|---|---|
| **良好** | không có điểm yếu, hoặc đã `fixed` / `accepted` (hiện riêng dòng 「修正・確認済み」) |
| **要確認** | có điểm yếu, không có mã nào thuộc nhóm 未認識 |
| **未認識** | có `missing_text`, `blank_page` hoặc `picture_no_desc` |

Hai mốc:
- **機械読取時 (lúc máy đọc xong)**: nhóm ở lần chấm đầu tiên, trước khi AI tự đọc lại và trước mọi chỉnh sửa của
  người — đo chất lượng OCR (so Docling / CU). Lưu ở trường `initial` của phần tử, không đổi khi người sửa; phần tử được
  dựng lại với nội dung khác (trang OCR lại / sửa Markdown cả trang) thì chấm lại. Dữ liệu cũ chưa có `initial` → suy từ điểm yếu hiện tại (`estimated` trong API).
- **現在 (hiện tại)**: sau khi người sửa / xác nhận — đo mức sẵn sàng của tài liệu.

% = số phần tử của nhóm / tổng phần tử nội dung của các trang đã đọc. Trang `failed` và trang chưa xử lý xong được
liệt kê riêng (không có phần tử để đếm).

Lấy số liệu: tab パイプライン (mục 認識結果 — bảng hai mốc + danh sách trang cần xử lý) ·
`GET /api/documents/{id}/recognition` · `python -m app.main status <doc_id>`.

## D. 品質 — hạng chất lượng trang / tài liệu

- Điểm trang (0–100) = 100 × confidence trung bình của phần tử nội dung (`fixed` / `accepted` tính 1.0, không có
  confidence tính 0.95) − phạt điểm yếu còn mở (error 12, warn 5, tối đa 60). Có điểm AI (「AIで5ページ採点」) → trung bình
  với điểm AI.
- Điểm tài liệu = 0.7 × trung bình điểm trang + 0.3 × điểm trang kém nhất.
- Hạng: **良好** ≥ 85 (`grade_good`) · **要注意** ≥ 60 (`grade_fair`) · **不良** < 60.

## E. Chunk — `ChunkStatus`

| Status | Nghĩa |
|---|---|
| `draft` (未承認) | vừa tạo / vừa sửa, chưa duyệt |
| `approved` (承認済み) | đã duyệt (người, すべて承認, hoặc tự duyệt) |
| `indexed` (インデックス済み) | đã nằm trong search |

**Cần xem (要確認)**: chunk vi phạm luật (thiếu mã mục, tách bảng, quá dài / quá ngắn…) hoặc confidence < 0.7
(`review.chunk_warn_below`).
