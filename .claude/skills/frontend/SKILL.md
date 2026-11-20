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
- Review chunk ở tab **チャンク** (`ChunksTab.tsx`): lọc 要確認, sửa, tách tại con trỏ, gộp với chunk sau, duyệt;
  popup 原本と比較 tô vùng của chunk trên trang gốc. Link cũ `/chunks` → tab チャンク.
- `ReviewGate`: nhắc review ở tab パイプライン + tab review tương ứng; 「すべて承認」 chỉ chạy sau popup xác nhận (ghi
  audit, người duyệt = người bấm) rồi chạy luôn bước sau.
