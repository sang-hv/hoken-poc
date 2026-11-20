import { useEffect, useMemo, useState } from "react";

/** Giá trị trễ `ms` sau lần thay đổi cuối — dùng cho ô tìm kiếm gọi API. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return v;
}

/** Phân trang phía client. Trang tự kẹp lại khi danh sách ngắn đi (lọc, xoá). */
export function useClientPage<T>(list: T[], page: number, size: number) {
  return useMemo(() => {
    const pages = Math.max(1, Math.ceil(list.length / size));
    const p = Math.min(Math.max(1, page), pages);
    return { items: list.slice((p - 1) * size, p * size), page: p, total: list.length };
  }, [list, page, size]);
}
