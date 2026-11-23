---
name: frontend
description: Quy ước UI khu A (React + Vite + TypeScript + Tailwind v4, component kiểu shadcn, i18n tiếng Anh/Nhật bắt buộc, live log SSE, màn review). Dùng khi sửa/thêm màn hình hoặc component trong web/.
---

# Frontend khu A — quy ước

## Chạy & kiểm tra
```bash
cd web && npm ci
npm run dev            # http://localhost:5173, proxy /api → API_URL (mặc định http://localhost:8000)
npx tsc -b && npm run build
```
Kiểm tra bằng Playwright (Chromium có sẵn): đi hết luồng Setup → upload → review → chunk, chụp cả `en` và `ja`,
sáng và tối (`localStorage hoken.lang`, `hoken.theme`), và không được có lỗi console.

## Bắt buộc
- Chữ hiển thị trạng thái phải khớp định nghĩa ở `docs/STATUS.md` (đổi định nghĩa → sửa cả hai).
- **Đọc `web/DESIGN.md` trước khi làm giao diện** (bố cục chia ngăn, thang chữ, khi nào dùng badge / banner / modal).
- **Mọi chữ hiển thị đi qua `t()`** và có ở cả `src/i18n/en.ts` và `src/i18n/ja.ts` (ja dùng kiểu `Messages` của en nên
  thiếu khoá là lỗi TypeScript). Không viết chuỗi cứng trong JSX.
- Màu dùng token (`bg-primary`, `text-muted-foreground`, `bg-warning-soft`...) định nghĩa trong `src/index.css`
  cho cả sáng và tối — không dùng mã màu trực tiếp.
- Component dùng chung ở `src/components/ui` (Button, Card, Badge, Select, Dialog, Tabs, Field...).
  `Field` tự gắn `id`/`htmlFor` cho label → giữ input là con duy nhất của `Field`.
- Nút chỉ có icon (hoặc ẩn nhãn ở màn hẹp) phải có `aria-label`.
- Gọi API qua `src/lib/api.ts` (tự gắn `X-Requested-With`, ném `ApiError` có `code`).
  Hiển thị lỗi bằng `useToastError()` / `useErrorText()` → dịch `errors.<code>`.

## Dữ liệu & live
- Server state: TanStack Query, key theo tài nguyên (`["document", id]`, `["pages", id]`, `["chunks", id]`).
- Live log: `useEventStream(url, onEvent)` (SSE, tự nối lại bằng Last-Event-ID); khi có sự kiện thì
  invalidate query liên quan (có throttle) thay vì polling dày.
- Nội dung log hiển thị bằng `useEventText()` (dịch `events.<code>` + `reasons.*`).

## Màn review (trong màn chi tiết tài liệu `pages/v2/DocumentViewer.tsx`, không còn màn riêng)
- Review OCR ở tab **検査** (`components/v2/viewer/InspectTab.tsx`): ảnh trang + khung phần tử, sửa / AI đọc lại
  từng phần tử; tài liệu duyệt tay có `PageApproval` (「このページを承認」, Ctrl/⌘+Enter → sang trang chưa duyệt kế tiếp,
  「承認を取り消す」). `/documents/:id/review` chuyển tới trang chưa duyệt đầu tiên; link cũ `/pages/:n` → tab 検査.
- Review chunk ở tab **チャンク** (`ChunksTab.tsx`): danh sách | nội dung | ngăn 原本 (`ChunkSourcePane`, tô vùng của
  chunk trên trang gốc). Lọc 要確認, sửa, tách tại con trỏ, gộp với chunk sau; 「承認して次へ」 (Ctrl/⌘+Enter), J/K đổi
  chunk. Thanh thao tác (kể cả 保存 khi đang sửa) luôn ở trên. Link cũ `/chunks` → tab チャンク.
- Tab **パイプライン** (`PipelineTab.tsx`): dải 8 bước ở trên (là tiêu đề tab), dải thao tác chỉ khi có việc (chạy lại
  trang lỗi / thử chat), dưới là 3 ngăn **rộng bằng nhau** 情報 | 認識結果 | 要対応ページ dựng bằng `viewer/pane.tsx`
  (cùng thanh tiêu đề h-10, cùng dòng h-9 kẻ dưới → thẳng hàng). Màn ≥ 1024px vừa một màn, chỉ ngăn dài tự cuộn.
  Bấm dòng 良好 / 要確認 / 未認識 / 計 ở 認識結果 → ngăn phải lọc đúng các trang đó (bấm lại / ✕ → về 要対応ページ);
  mỗi trang mở tab 検査 ở trang đó.
- `ReviewGate`: dải banner một dòng dưới thanh trên ở tab パイプライン + tab review tương ứng. `ReviewPrompt` chỉ bật
  popup khi pipeline vừa dừng ở bước review lúc đang xem tab パイプライン (không bật khi mở / tải lại màn).
  「すべて承認」 chỉ chạy sau hộp xác nhận (ghi audit, người duyệt = người bấm) rồi chạy luôn bước sau.
