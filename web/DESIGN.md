# Design system — UI khu A

Nền: **shadcn/ui-style** (Radix primitives + `class-variance-authority` + Tailwind v4), component ở
`src/components/ui`, token ở `src/index.css`. Không thêm thư viện UI thứ hai.
Chuẩn bố cục lấy theo màn chi tiết tài liệu (tab 原本 / テキスト / 検査): **workspace chia ngăn**, không phải dashboard.

Khi Apotool (Stransa) đưa style guide / Figma: chỉ đổi token trong `index.css` (màu, font, bo góc) — component và
quy tắc dưới đây giữ nguyên.

## 1. Bố cục
- Màn làm việc = các **ngăn cao hết màn**, ngăn cách bằng `border-border` 1px. Không bọc vùng lớn trong `Card` nổi,
  không `max-w-*` + căn giữa cho màn công cụ (chỉ dùng cho vùng đọc: `max-w-3xl`).
- Thanh công cụ của ngăn: `h-11` (hoặc `min-h-11` khi có thể xuống dòng), `bg-card`, `border-b`, `px-3`–`px-4`.
- Vùng xem tài liệu / ảnh trang: `bg-muted/40`. Panel phụ bên phải: `w-80` (tối đa `26rem`), `bg-card`, `border-l`.
- Thông tin dạng nhãn–giá trị: `<dl>` hai cột (nhãn `text-muted-foreground`, giá trị `text-foreground`), như `InfoPanel`.
- Danh sách: dòng phân cách bằng `border-b`, hover `bg-accent/60`, đang chọn `bg-accent` + vạch trái 2px `bg-primary`.
- Nhiều ngăn đặt cạnh nhau: chia **bằng nhau** (`grid-cols-*`, ngăn cách `gap-px bg-border`), mọi ngăn dùng
  `Pane` / `PaneHeader` / `PaneRow` (`components/v2/viewer/pane.tsx`) để tiêu đề và các dòng thẳng hàng. Nhãn cột đặt
  trên thanh tiêu đề, không thêm dòng tiêu đề cột. Không lồng ngăn trong ngăn, không đặt bảng có `max-w` trong ngăn rộng.
- Không dùng `Card` nổi (bóng đổ) cho vùng nội dung. Vùng nhóm nội dung = `rounded-lg border border-border bg-card`.

### Hai loại màn
| Loại | Màn | Bố cục |
|---|---|---|
| **Công cụ** (làm việc liên tục) | chi tiết tài liệu, チャット | tràn màn (AppShell `fullBleed`), thanh trên `h-11`–`h-12`, các ngăn chia bằng viền |
| **Quản trị / danh sách** | 文書, ダッシュボード, ユーザー, 設定, 監査ログ | `PageHeader` + nội dung `max-w-7xl` |

Màn quản trị:
- **Danh sách**: một khung viền; thanh lọc ở đầu (ô tìm có icon + `FilterChips` + select phụ); bảng dòng `border-b`, hover
  `bg-accent/40`; thao tác phụ của dòng (sửa tên, bật/tắt, xoá) trong menu 「…」; trạng thái = chấm màu + chữ.
- **Dashboard**: dải số liệu chia ô (`gap-px` trên nền `bg-border`), không icon trong ô; danh sách việc cần làm;
  panel phải là các `<dl>` ngăn bằng đường kẻ.
- **Cài đặt**: mỗi mục là `SettingsSection` — tiêu đề + mô tả cột trái (16rem), form trong khung viền cột phải, nút
  lưu ở chân khung (`bg-muted/30`). Tab cấp trang dùng `TabsList variant="line"` (gạch chân), không icon.
  Cấu hình đặt bằng biến môi trường (dịch vụ AI, SSO) không có màn xem: thiếu biến dịch vụ AI thì dải cảnh báo
  ở ダッシュボード (chỉ admin) báo đúng tên biến. 設定 chỉ giữ vài ngưỡng người vận hành cần chỉnh.
- **Tên công nghệ không lên giao diện**: dùng tên vai trò 標準解析 / Parser (Docling), 精密解析 / Layout Analyzer
  (Content Understanding), VLM (model đọc ảnh). Code, biến môi trường `CU_*`, mã log giữ tên cũ.
- Bật/tắt có hậu quả (loại tài liệu khỏi tìm kiếm, khoá đăng nhập) đi qua menu + hộp xác nhận, không đặt công tắc
  trên từng dòng. Bật lại thì không cần xác nhận.

## 2. Chữ
| Token | Cỡ | Dùng cho |
|---|---|---|
| `text-xs` | 12 | nhãn phụ, meta, số trang, log |
| `text-dense` | 13 | nội dung dày (log, danh sách phần tử, textarea mono) |
| `text-sm` | 14 | **mặc định** của giao diện |
| `text-reading` | 15 / dòng 1.9 | đọc nội dung tài liệu (テキスト, nội dung chunk) |
| `.prose-compact` | 12 | markdown trích đoạn (căn cứ ở チャット): tiêu đề không to hơn chữ thường |
| `text-base` | 16 | tiêu đề trang nhỏ |
| `text-lg`–`text-xl` | 18–20 | tiêu đề màn (hiếm) |

- **Không dùng `text-[Npx]` / `leading-[…]` tuỳ ý** — thiếu cỡ thì thêm token vào `@theme` trong `index.css`.
- Đậm: `font-medium` cho nhấn mạnh, `font-semibold` chỉ cho tiêu đề ngăn / mã định danh. Không dùng `font-bold`.
- Số: luôn `tabular-nums`. Mã mục (M015-2…): `font-mono font-semibold`, **là chữ, không bọc trong pill**.
- Tiếng Nhật: `palt` đã bật ở `body`; đoạn đọc dùng `text-reading`.

## 3. Màu
- Màu ngữ nghĩa (`success` / `warning` / `danger` / `info`) **chỉ để báo trạng thái**. `primary` cho hành động chính và
  lựa chọn đang bật. `violet` chỉ cho nhãn loại phần tử ở 検査 — không dùng làm "màu AI".
- Mặc định là màu trung tính; chỉ tô khi có điều cần chú ý (vd. độ tin cậy < 70% mới đổi màu chữ, ≥ 70% để thường).
- Nền tô màu cả khối (`bg-*-soft`) chỉ cho **banner cấp trang** (một dải dưới thanh trên). Trong nội dung, cảnh báo
  dùng vạch trái `border-l-2 border-warning pl-3`, không dùng hộp tô nền.
- Không dùng màu mã hex trực tiếp; mọi màu qua token, có cả sáng và tối.

## 4. Badge, icon
- `Badge` chỉ cho **trạng thái** (状態, 品質, 承認済み). Tối đa 1–2 badge trong một vùng nhìn. Điểm số, số đếm,
  mã, số trang là chữ thường.
- Bộ lọc dạng chip: dùng `FilterChips` (`components/ui`) — cùng một kiểu ở mọi danh sách, có số đếm, số tô
  `warning` / `danger` khi đó là nhóm cần chú ý.
- Icon chỉ khi giúp nhận diện hành động hoặc trạng thái. Không gắn icon cho mọi nút / mọi dòng log.
  Không dùng `Sparkles` / `Wand2` cho nút thường — "do AI làm" nói bằng chữ khi cần.
- Nút chỉ có icon phải có `aria-label` (+ `title` hoặc `Tip`).

- Mã kỹ thuật (mã thao tác audit, khoá cấu hình, tên hàng đợi) hiện kèm nhãn dễ đọc: nhãn ở trên, mã `font-mono
  text-xs text-muted-foreground` ở dưới.

## 5. Thông báo, banner, modal
| Tình huống | Dùng |
|---|---|
| Trạng thái của cả tài liệu (chờ review, đang xử lý) | **một** dải banner dưới thanh trên (`ReviewGate`) |
| Kết quả thao tác (đã lưu, đã xếp hàng) | toast (`sonner`) |
| Cảnh báo trong nội dung | vạch trái `border-l-2`, chữ thường |
| Cần người quyết định trước khi làm (xoá, すべて承認) | `Dialog` xác nhận |
| Xem / so sánh nội dung lớn | **ngăn trong màn** (vd. 原本 ở tab チャンク), không dùng modal toàn màn |

- **Không tự mở modal khi tải trang.** Popup chỉ được bật khi trạng thái vừa đổi trong lúc người dùng đang xem
  (vd. pipeline vừa dừng ở bước review), và banner vẫn là nơi chính.
- Không chồng nhiều banner: một màn tối đa một dải banner.
- Dialog: tiêu đề là câu hỏi ("すべてのチャンクを承認しますか？"), thân là hậu quả, footer tối đa 2 nút + 1 nút phụ.
  Nút chính hoặc ô xác nhận có `data-autofocus` (Dialog tự focus, không rơi vào nút ✕).
- Thao tác nguy hiểm: một câu hậu quả + checkbox xác nhận + nút `danger`. Không thêm hộp đỏ tô nền.

## 6. Thao tác
- Màn review phải dùng được bằng bàn phím: ←/→ đổi trang (原本 / 検査), J/K đổi chunk, Ctrl/⌘+Enter = duyệt và sang
  mục chưa duyệt kế tiếp. Gợi ý phím hiện ở chân ngăn bằng `Kbd`.
- Thanh thao tác của mục đang sửa luôn nhìn thấy (đặt ở thanh công cụ của ngăn), không đặt dưới textarea dài.

## 7. Kiểm tra
Playwright 1440×900 và 390×844, `ja` + `en`, sáng + tối, không lỗi console (xem `.claude/skills/frontend`).
