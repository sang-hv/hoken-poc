/** Danh sách chunk của tab チャンク cho tài liệu lớn (hàng nghìn chunk):
 *  - Server phân trang / lọc / tìm (`GET /documents/{doc}/chunks/list`), chỉ trả tóm tắt (không có nội dung đầy đủ).
 *  - Danh sách ảo: dòng cao cố định, chỉ vẽ các dòng đang thấy (+ dư vài dòng), tải theo khối 100 dòng khi cuộn tới.
 *  - Nhảy tới một chunk bất kỳ (`scrollToIndex`) mà không cần tải các khối ở giữa. */
import { useQueries, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Check } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { ChunkListPage, ChunkSummary } from "@/lib/v2types";
import { cn } from "@/lib/utils";

export const ROW = 76; // px — mọi dòng cao bằng nhau (danh sách ảo)
export const BLOCK = 100;
const OVERSCAN = 6;

export type ChunkFilter = "all" | "issues";
export interface ChunkListParams {
  filter: ChunkFilter;
  q: string;
  page: number | null; // trang PDF
}

/** Mọi key danh sách chunk bắt đầu bằng ["chunks-list", doc] — KHÔNG nằm dưới ["inspect", doc] để không bị tải lại
 *  theo mọi sự kiện; chỉ làm mới khi có sự kiện về chunk (xem DocumentViewer). */
export const ck = {
  list: (doc: string) => ["chunks-list", doc] as const,
  block: (doc: string, p: ChunkListParams, block: number) => ["chunks-list", doc, p.filter, p.q, p.page, block] as const,
  focus: (doc: string, p: ChunkListParams, id: string) => ["chunks-list", doc, p.filter, p.q, p.page, "focus", id] as const,
  one: (doc: string, id: string) => ["chunk", doc, id] as const,
};

export function listUrl(doc: string, p: ChunkListParams, offset: number, limit: number, focus = "") {
  const s = new URLSearchParams({ offset: String(offset), limit: String(limit), filter: p.filter });
  if (p.q) s.set("q", p.q);
  if (p.page) s.set("page", String(p.page));
  if (focus) s.set("focus", focus);
  return `/documents/${doc}/chunks/list?${s}`;
}

/** Khối đầu: tổng số + số đếm + 100 dòng đầu. */
export function useChunkHead(doc: string, p: ChunkListParams, enabled = true) {
  return useQuery({
    queryKey: ck.block(doc, p, 0),
    queryFn: () => api.get<ChunkListPage>(listUrl(doc, p, 0, BLOCK)),
    enabled,
  });
}

/** Vị trí của chunk trong danh sách đã lọc (null = không có trong danh sách). */
export function useChunkIndex(doc: string, p: ChunkListParams, id: string | null) {
  return useQuery({
    queryKey: ck.focus(doc, p, id ?? ""),
    queryFn: () => api.get<ChunkListPage>(listUrl(doc, p, 0, 1, id ?? "")),
    enabled: !!id,
    select: (r) => r.focus_index,
  });
}

export function ChunkList({
  docId,
  params,
  total,
  selectedId,
  onSelect,
  scrollToIndex,
  pdfRange,
  weak,
}: {
  docId: string;
  params: ChunkListParams;
  total: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** cuộn tới dòng này nếu đang không thấy */
  scrollToIndex: number | null;
  pdfRange: (s: ChunkSummary) => [number, number];
  weak: (s: ChunkSummary) => boolean;
}) {
  const { t } = useTranslation();
  const box = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ top: 0, h: 600 });

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setView((v) => ({ ...v, h: el.clientHeight })));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // Đổi bộ lọc / tìm → về đầu danh sách
  useEffect(() => {
    if (box.current) box.current.scrollTop = 0;
    setView((v) => ({ ...v, top: 0 }));
  }, [params.filter, params.q, params.page]);
  useEffect(() => {
    const el = box.current;
    if (!el || scrollToIndex === null || scrollToIndex < 0) return;
    const y = scrollToIndex * ROW;
    if (y < el.scrollTop || y + ROW > el.scrollTop + el.clientHeight) el.scrollTop = Math.max(0, y - el.clientHeight / 2 + ROW / 2);
  }, [scrollToIndex]);

  const start = Math.max(0, Math.floor(view.top / ROW) - OVERSCAN);
  const end = Math.min(total, Math.ceil((view.top + view.h) / ROW) + OVERSCAN);
  const blocks = useMemo(() => {
    const out: number[] = [];
    for (let b = Math.floor(start / BLOCK); b <= Math.floor(Math.max(start, end - 1) / BLOCK); b++) out.push(b);
    return out;
  }, [start, end]);
  const results = useQueries({
    queries: blocks.map((b) => ({
      queryKey: ck.block(docId, params, b),
      queryFn: () => api.get<ChunkListPage>(listUrl(docId, params, b * BLOCK, BLOCK)),
      staleTime: 30_000,
    })),
  });
  const rowAt = (i: number): ChunkSummary | undefined => {
    const k = blocks.indexOf(Math.floor(i / BLOCK));
    return k < 0 ? undefined : results[k]?.data?.items[i - Math.floor(i / BLOCK) * BLOCK];
  };

  const rows = [];
  for (let i = start; i < end; i++) {
    const c = rowAt(i);
    rows.push(
      <li key={c?.id ?? `i${i}`} className="absolute inset-x-0 border-b border-border" style={{ top: i * ROW, height: ROW }}>
        {c ? (
          <Row c={c} active={c.id === selectedId} onSelect={onSelect} range={pdfRange(c)} weak={weak(c)} />
        ) : (
          <div className="space-y-2 px-3 py-2.5">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className="h-3.5 w-3/4" />
          </div>
        )}
      </li>,
    );
  }

  return (
    <div
      ref={box}
      onScroll={(e) => setView({ top: e.currentTarget.scrollTop, h: e.currentTarget.clientHeight })}
      className="min-h-0 flex-1 overflow-y-auto"
      aria-label={t("viewer.chunkTab.listLabel", { n: total })}
    >
      <ul className="relative" style={{ height: total * ROW }}>
        {rows}
      </ul>
    </div>
  );
}

/** Màu chữ cho độ tin cậy: chỉ tô khi thấp — số bình thường để màu trung tính. */
export function confidenceClass(v: number) {
  return v < 0.5 ? "text-danger" : v < 0.7 ? "text-warning" : "text-muted-foreground";
}

/** "p.3" hoặc "p.3–5" */
export function usePageLabel() {
  const { t } = useTranslation();
  return ([a, b]: [number, number]) => (a === b ? t("viewer.page.short", { page: a }) : t("viewer.chunks.pages", { from: a, to: b }));
}

function Row({
  c,
  active,
  onSelect,
  range,
  weak,
}: {
  c: ChunkSummary;
  active: boolean;
  onSelect: (id: string) => void;
  range: [number, number];
  weak: boolean;
}) {
  const { t } = useTranslation();
  const pages = usePageLabel();
  return (
    <button
      type="button"
      onClick={() => onSelect(c.id)}
      aria-current={active}
      data-chunk={c.id}
      className={cn(
        "relative flex h-full w-full cursor-pointer flex-col justify-center gap-0.5 px-4 text-left transition-colors hover:bg-accent/60",
        active && "bg-accent before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:bg-primary",
      )}
    >
      <span className="flex items-baseline gap-2 text-xs">
        <span className="tabular-nums text-muted-foreground">#{c.seq}</span>
        {c.item_code && <span className="font-mono font-semibold">{c.item_code}</span>}
        <span className="flex-1" />
        {weak && (
          <span title={t("viewer.chunkTab.weak")} className="self-center">
            <AlertTriangle className="size-3.5 shrink-0 text-warning" aria-label={t("viewer.chunkTab.weak")} />
          </span>
        )}
        <span className="shrink-0 tabular-nums text-muted-foreground">{pages(range)}</span>
      </span>
      <span className={cn("truncate text-sm", active && "font-medium", !c.title && "text-muted-foreground")}>
        {c.title || t("viewer.chunks.untitled")}
      </span>
      <span className="flex min-w-0 items-center gap-2 text-xs">
        {c.status !== "draft" && (
          <Check className="size-3.5 shrink-0 text-success" aria-label={t(`viewer.chunkTab.status.${c.status}`)} />
        )}
        <span className={cn("shrink-0 tabular-nums", confidenceClass(c.confidence))}>{Math.round(c.confidence * 100)}%</span>
        {c.violations.length > 0 && (
          <span className="shrink-0 text-warning">
            {c.violations.length === 1
              ? t(`violations.${c.violations[0]}`, { defaultValue: c.violations[0] })
              : t("viewer.chunkTab.rules", { count: c.violations.length })}
          </span>
        )}
        <span className="truncate text-muted-foreground">{c.preview}</span>
      </span>
    </button>
  );
}
