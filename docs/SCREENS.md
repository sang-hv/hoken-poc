# Danh sách màn hình & tính năng (khu A — nạp tài liệu)

Tài liệu ngắn để giải thích cho PM viết tài liệu layout. Mỗi màn: **mục đích → bố cục → tính năng**.
Giao diện có tiếng Nhật / tiếng Anh, nền sáng / tối. Định nghĩa trạng thái: `docs/STATUS.md`.

**Tên bước đọc tài liệu** (giao diện không ghi tên sản phẩm, để sau này đổi công nghệ không phải đổi màn hình):

| Giao diện (ja / en) | Vai trò | Công nghệ hiện tại |
|---|---|---|
| 標準解析 / Parser | đọc mọi trang, chấm điểm | Docling (OCR bằng RapidOCR tiếng Nhật) |
| 精密解析 / Layout Analyzer | đọc kỹ trang khó (scan, bảng gộp ô) | Azure Content Understanding |
| VLM | đọc lại phần tử ⚠, chuyển hình thành chữ | model ảnh + chữ của LLM |

**Vai trò**
- **Viewer** chỉ xem.
- **Reviewer** được upload, review OCR / chunk, chạy lại job, chat thử.
- **Admin** làm được hết, cộng thêm ba màn quản lý: 設定, ユーザー, 監査ログ.

---

## 0. Khung chung (mọi màn sau khi đăng nhập)
- **Sidebar trái**, chia 3 nhóm:
  - 運用: ダッシュボード, 文書
  - テスト: ボットとチャット (reviewer trở lên)
  - 管理: 設定, ユーザー, 監査ログ (chỉ admin)
- Sidebar thu gọn được; trên điện thoại sidebar thành menu ☰.
- **Thanh trên**: đổi ngôn ngữ 日本語 / English, đổi sáng / tối, tên và vai trò người dùng (menu đăng xuất, đổi mật khẩu).

## 1. Setup (chỉ lần chạy đầu)
- Tạo tài khoản admin đầu tiên (email, tên, mật khẩu).
- Tạo xong thì vào thẳng màn 設定.

## 2. Đăng nhập
- Đăng nhập bằng email + mật khẩu.
- Có thêm nút Google / Microsoft nếu SSO đã bật (bật bằng biến môi trường `AUTH_GOOGLE_*` / `AUTH_ENTRA_*`, xem `.env.example`).

## 3. ダッシュボード — "việc gì cần làm ngay"
- **Dải cảnh báo** (chỉ admin thấy, chỉ khi có vấn đề):
  - đỏ: mất kết nối DB / blob / queue → liên hệ DevOps
  - vàng: dịch vụ AI nào chưa cấu hình, kèm tên biến môi trường còn thiếu
- **Dải 4 số liệu**; 3 ô đầu bấm vào thì mở danh sách đã lọc sẵn:
  - số tài liệu
  - trang cần review
  - chunk cần review
  - job đang chạy (kèm số job lỗi nếu có)
- **Danh sách tài liệu cần xử lý**: tài liệu đang chờ review hoặc có lỗi, kèm bước tiếp theo.
- **Panel phải**:
  - số tài liệu theo từng giai đoạn
  - độ dài hàng đợi
  - lỗi gần đây
  - tình trạng dịch vụ AI (đã / chưa cấu hình)

## 4. 文書 — danh sách tài liệu
- **Thanh lọc**:
  - tìm theo tên
  - trạng thái: すべて / 要対応 / 処理中 / インデックス済み / エラーあり
  - loại tài liệu (赤本, 緑本…)
  - nút xoá lọc
- **Bảng**, mỗi dòng gồm:
  - tên + loại + số trang
  - trạng thái
  - **bước tiếp theo**, bấm là đi tới đúng chỗ (vd 「OCR レビュー · 残り 3」, 「エラーを見る」)
  - thời gian cập nhật
- **Menu ⋯ trên từng dòng**:
  - đổi tên
  - loại khỏi tìm kiếm / đưa lại vào tìm kiếm (có hộp xác nhận; chatbot sẽ không dùng tài liệu đó nữa)
  - xoá (có hộp xác nhận)
- **Nút "Upload PDF"** mở hộp thoại:
  - kéo thả PDF hoặc ảnh
  - tên hiển thị
  - loại tài liệu
  - số trang sách bắt đầu (dùng khi trích dẫn, vd P536)
  - khoảng trang PDF cần xử lý
  - nhắc: chỉ tài liệu công khai của MHLW
- Upload xong, pipeline **tự chạy**.

## 5. Chi tiết tài liệu (màn chính)
**Thanh trên của màn**:
- ← về danh sách
- tên tài liệu
- **6 tab**: パイプライン · 原本 · テキスト · インサイト · 検査 · チャンク
- menu その他: mở / tải PDF gốc

**Dải banner vàng**: chỉ hiện khi pipeline đang **dừng chờ review**.
- Chữ: 「OCR レビュー待ち」 hoặc 「チャンクレビュー待ち」, kèm tiến độ duyệt.
- Hai nút: 「すべて承認」 (có hộp xác nhận, ghi audit) và 「ページをレビュー」 / 「チャンクをレビュー」.
- Pipeline vừa dừng lúc người dùng đang xem thì bật thêm popup hỏi Review hay すべて承認.

### 5.1 Tab パイプライン — tổng quan tài liệu (vừa 1 màn hình)
- **Dải 8 bước** ở trên cùng: 標準解析 → 振り分け → 精密解析 → ページ結合 → OCR レビュー → チャンク化 → チャンクレビュー → インデックス.
  - Mỗi bước hiện trạng thái (完了 / 処理中 / 対応待ち / 待機 / 失敗) và số lượng.
  - Rê chuột vào bước để xem giải thích.
- **Dải thao tác**, chỉ hiện khi có việc:
  - 「N ページの読み取りに失敗」 + nút chạy lại trang lỗi; hoặc
  - 「インデックス済み」 + nút thử chat.
- **3 ngăn rộng bằng nhau**:
  1. **情報**:
     - trạng thái
     - loại tài liệu
     - trang sách / trang PDF
     - số trang gửi CU
     - chất lượng (điểm + 「弱点 N 件 ›」)
     - phiên bản cài đặt
     - nút đổi tên
  2. **認識結果**:
     - % phần tử 良好 / 要確認 / 未認識, đặt cạnh nhau ở hai mốc **現在** (sau khi người sửa) và **機械読取時** (ngay sau OCR)
     - **bấm một dòng** thì ngăn 3 lọc ra đúng các trang thuộc nhóm đó; dòng 計 = mọi trang
  3. **要対応ページ**:
     - mặc định chỉ liệt kê trang còn 未認識 / 要確認 / lỗi, trang nặng nhất lên đầu
     - bấm một trang thì mở tab 検査 ở đúng trang đó
     - tài liệu vài trăm trang thì ngăn này tự cuộn
- **ライブログ** ở dưới cùng: log chạy pipeline theo thời gian thực; thu gọn được.

### 5.2 Tab 原本 — xem PDF gốc
- Ảnh từng trang, có cột thumbnail.
- Phóng to / thu nhỏ; ← → để đổi trang; nhảy tới trang.

### 5.3 Tab テキスト — văn bản đã đọc
- Văn bản sau khi OCR + nối trang, chia theo từng trang.

### 5.4 Tab インサイト — tóm tắt bằng AI
- AI viết tóm tắt + các ý chính của tài liệu.
- Nút tạo / tạo lại. Có ghi chú "AI tạo, cần kiểm tra lại".

### 5.5 Tab 検査 — review OCR từng trang
- **Giữa**: ảnh trang với khung bao từng phần tử (tiêu đề, đoạn văn, bảng, hình…); khung màu theo trạng thái.
- **Thanh chất lượng**:
  - điểm trang / tài liệu
  - trang tệ nhất
  - 「AI で弱点を修正 (N)」: AI đọc lại hàng loạt; có thể sửa prompt cho lần chạy đó
  - 「AI で 5 ページを採点」
- **Panel phải**, 4 tab:
  - **要素**: danh sách phần tử, lọc tất cả / ⚠ / đã sửa
  - **チャンク**: các chunk đi qua trang này
  - **弱点**: các điểm ⚠ còn mở / đã xử lý
  - **履歴**: lịch sử sửa
- **Chi tiết phần tử**:
  - ảnh cắt từ bản gốc đặt cạnh kết quả đọc, lý do bị ⚠, confidence, nguồn đọc (標準解析 / 精密解析 / VLM)
  - nút **編集** (sửa tay), **AI で再読込** (thêm chỉ dẫn được), **問題なし** (xác nhận đúng), JSON
- **Duyệt trang** (chế độ duyệt tay): 「このページを承認」, phím Ctrl/⌘ + Enter, rồi tự sang trang chưa duyệt kế tiếp. Có nút hoàn tác.
- Đọc lại cả trang bằng AI.
- Sửa xong thì hệ thống **tự chunk + index lại**.

### 5.6 Tab チャンク — review chunk
- **3 cột**:
  1. **Danh sách chunk**:
     - tìm theo mã mục / nội dung
     - lọc theo trang
     - lọc 要確認 (vi phạm luật / confidence thấp)
     - chịu được danh sách rất dài
  2. **Nội dung chunk**:
     - mã mục, trang, confidence, người sửa
     - nút **編集**, **カーソル位置で分割**, **次と結合**
     - 「承認して次へ」 (Ctrl/⌘ + Enter); J / K để chuyển chunk
  3. **原本**: trang gốc, tô vùng thuộc chunk; ẩn / hiện được.
- Lưu xong thì search index tự cập nhật.

## 6. ボットとチャット — chat thử (khu B bản test)
- **Trái**: khung chat với câu hỏi mẫu. Câu trả lời có trích dẫn [1], [2].
  - Không tìm thấy căn cứ → hiện 「サポート窓口へ引き継ぎ」.
  - Hiện thời gian tìm kiếm / gọi LLM.
- **Phải**: các đoạn tài liệu đã đưa cho bot; đoạn được dùng gắn nhãn 「引用」.
- **Kiểm tra độ ổn định**: hỏi cùng một câu 3 lần.
- Nhắc: chỉ để thử, câu hỏi **không lưu, không ghi log**.

## 7. 設定 (admin)
- Một bảng nhỏ 3 dòng — **工程 · 動作 · 信頼度がこれ未満 (%)**:
  | 工程 | 動作 | mặc định |
  |---|---|---|
  | OCR | AI で読み直す | 60% |
  | OCR | ⚠ を付けてレビューへ | 80% |
  | チャンク化 | ⚠ を付けてレビューへ | 70% |
- Đặt 「AI で読み直す」 cao hơn ngưỡng review thì báo lỗi, không cho lưu.
- Pipeline luôn tự chạy, chỉ dừng ở review khi có cảnh báo; trang khó luôn qua 精密解析.
- Mọi cấu hình khác (dịch vụ AI, SSO, hạ tầng, prompt, luật chunk…) đặt bằng biến môi trường hoặc cố định trong code,
  không hiện trên giao diện.

## 8. ユーザー (admin)
- Bảng người dùng gồm:
  - tên, email
  - vai trò
  - cách đăng nhập (mật khẩu / Google / Entra)
  - trạng thái
  - lần đăng nhập cuối
- Lọc theo vai trò, tìm theo tên / email.
- Thêm người dùng; để trống mật khẩu = chỉ đăng nhập SSO.
- Đổi vai trò. Khoá / mở đăng nhập (có xác nhận; lịch sử vẫn giữ trong audit). Xoá.
- Bảng giải thích quyền của từng vai trò.

## 9. 監査ログ (admin)
- Ai làm gì, lúc nào, gồm:
  - upload / xoá tài liệu
  - duyệt trang / chunk, すべて承認
  - sửa phần tử
  - đổi cài đặt pipeline
  - thêm / sửa người dùng
- Tìm theo người, hành động, đối tượng.
