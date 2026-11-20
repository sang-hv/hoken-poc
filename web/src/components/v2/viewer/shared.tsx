/** Dùng chung cho màn chi tiết nguồn: query key, hook đọc dữ liệu, màu theo loại phần tử, chip hạng / điểm yếu. */
import { type QueryClient, useQuery } from "@tanstack/react-query";
import { AlertTriangle, RotateCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useErrorText } from "@/components/common";
import { Badge, Button, type Tone } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Chunk } from "@/lib/types";
import type {
  DocInfo,
  DocQuality,
  ElementLabel,
  ElementStatus,
  HistoryItem,
  Insights,
  PageElements,
  PageText,
  QualityGrade,
  WeakCode,
  WeakItem,
} from "@/lib/v2types";
import { cn } from "@/lib/utils";

export type ViewerTab = "pipeline" | "original" | "text" | "insights" | "inspect";
export const VIEWER_TABS: ViewerTab[] = ["pipeline", "original", "text", "insights", "inspect"];
export type PanelTab = "elements" | "chunks" | "weak" | "history";

/* ---------------------------------------------------------------- Query keys
 * Mọi key của màn này bắt đầu bằng ["inspect", docId] → invalidate cả màn bằng một key. */
export const vk = {
  all: (doc: string) => ["inspect", doc] as const,
  info: (doc: string) => ["inspect", doc, "info"] as const,
  text: (doc: string) => ["inspect", doc, "text"] as const,
  insights: (doc: string) => ["inspect", doc, "insights"] as const,
  quality: (doc: string) => ["inspect", doc, "quality"] as const,
  weak: (doc: string) => ["inspect", doc, "weak"] as const,
  elements: (doc: string, page: number) => ["inspect", doc, "elements", page] as const,
  raw: (doc: string, page: number, eid: string) => ["inspect", doc, "raw", page, eid] as const,
  chunks: (doc: string, page: number) => ["inspect", doc, "chunks", page] as const,
  history: (doc: string, page: number) => ["inspect", doc, "history", page] as const,
  pages: (doc: string) => ["pages", doc] as const, // dùng chung với màn cũ
};

/** Sau khi sửa / đọc lại / xác nhận một phần tử: làm mới những gì phụ thuộc vào nó. */
export function invalidateAfterEdit(qc: QueryClient, doc: string, page: number) {
  for (const key of [
    vk.elements(doc, page),
    vk.quality(doc),
    vk.weak(doc),
    vk.history(doc, page),
    vk.text(doc),
    vk.chunks(doc, page),
  ])
    qc.invalidateQueries({ queryKey: key });
}

/** Không thử lại với 4xx (404 / 403 là câu trả lời, không phải lỗi mạng). */
const noRetry4xx = (count: number, e: unknown) => !(e instanceof ApiError && e.status < 500) && count < 2;

export function useDocInfo(doc: string) {
  return useQuery({ queryKey: vk.info(doc), queryFn: () => api.get<DocInfo>(`/documents/${doc}/info`), retry: noRetry4xx });
}
export function useQuality(doc: string, poll = false) {
  return useQuery({
    queryKey: vk.quality(doc),
    queryFn: () => api.get<DocQuality>(`/documents/${doc}/quality`),
    retry: noRetry4xx,
    refetchInterval: poll ? 4000 : false,
  });
}
export function useWeak(doc: string, poll = false) {
  return useQuery({
    queryKey: vk.weak(doc),
    queryFn: () => api.get<WeakItem[]>(`/documents/${doc}/weak`),
    retry: noRetry4xx,
    refetchInterval: poll ? 4000 : false,
  });
}
export function useElements(doc: string, page: number, poll = false) {
  return useQuery({
    queryKey: vk.elements(doc, page),
    queryFn: () => api.get<PageElements>(`/documents/${doc}/pages/${page}/elements`),
    enabled: page > 0,
    retry: noRetry4xx,
    refetchInterval: poll ? 4000 : false,
  });
}
export function usePageText(doc: string) {
  return useQuery({ queryKey: vk.text(doc), queryFn: () => api.get<PageText[]>(`/documents/${doc}/text`), retry: noRetry4xx });
}
/** 404 {code: no_insights} → `null` (chưa tạo), không phải lỗi. */
export function useInsights(doc: string) {
  return useQuery({
    queryKey: vk.insights(doc),
    queryFn: async () => {
      try {
        return await api.get<Insights>(`/documents/${doc}/insights`);
      } catch (e) {
        if (e instanceof ApiError && (e.code === "no_insights" || e.status === 404)) return null;
        throw e;
      }
    },
    retry: noRetry4xx,
  });
}
export function usePageChunks(doc: string, page: number) {
  return useQuery({
    queryKey: vk.chunks(doc, page),
    queryFn: () => api.get<Chunk[]>(`/documents/${doc}/pages/${page}/chunks`),
    enabled: page > 0,
    retry: noRetry4xx,
  });
}
export function useHistory(doc: string, page: number) {
  return useQuery({
    queryKey: vk.history(doc, page),
    queryFn: () => api.get<HistoryItem[]>(`/documents/${doc}/pages/${page}/history`),
    enabled: page > 0,
    retry: noRetry4xx,
  });
}

export const pageImageUrl = (doc: string, page: number) => `/api/documents/${doc}/pages/${page}/image`;
export const elementImageUrl = (doc: string, page: number, eid: string, v = "") =>
  `/api/documents/${doc}/pages/${page}/elements/${eid}/image${v ? `?v=${encodeURIComponent(v)}` : ""}`;

/* ---------------------------------------------------------------- Màu theo loại phần tử
 * Chuỗi class viết đầy đủ để Tailwind quét được. */
interface LabelColor {
  border: string;
  badge: string; // nền đặc + chữ trắng cho số thứ tự
  fill: string; // tô khi hover
  chip: string; // chip nhãn nhẹ
}
const C = {
  violet: { border: "border-violet", badge: "bg-violet text-white", fill: "bg-violet/15", chip: "bg-violet-soft text-violet" },
  info: { border: "border-info", badge: "bg-info text-white", fill: "bg-info/15", chip: "bg-info-soft text-info" },
  success: { border: "border-success", badge: "bg-success text-white", fill: "bg-success/15", chip: "bg-success-soft text-success" },
  primary: { border: "border-primary", badge: "bg-primary text-primary-foreground", fill: "bg-primary/15", chip: "bg-primary-soft text-primary" },
  warning: { border: "border-warning", badge: "bg-warning text-white", fill: "bg-warning/20", chip: "bg-warning-soft text-[color:var(--warning)] dark:text-warning" },
  grey: { border: "border-muted-foreground/70", badge: "bg-muted-foreground text-background", fill: "bg-muted-foreground/15", chip: "bg-muted text-muted-foreground" },
} satisfies Record<string, LabelColor>;

export const LABEL_COLOR: Record<ElementLabel, LabelColor> = {
  title: C.violet,
  section_header: C.info,
  text: C.info,
  toc: C.success,
  list: C.success,
  table: C.primary,
  picture: C.warning,
  formula: C.grey,
  caption: C.grey,
  footnote: C.grey,
  page_header: C.grey,
  page_footer: C.grey,
};
export const labelColor = (l: string): LabelColor => LABEL_COLOR[l as ElementLabel] ?? C.grey;

/* ---------------------------------------------------------------- Chip */
export const GRADE_TONE: Record<QualityGrade, Tone> = { good: "success", fair: "warning", poor: "danger" };
export const GRADE_DOT: Record<QualityGrade, string> = { good: "bg-success", fair: "bg-warning", poor: "bg-danger" };

export function GradeChip({ grade, score, className }: { grade: QualityGrade; score?: number; className?: string }) {
  const { t } = useTranslation();
  return (
    <Badge tone={GRADE_TONE[grade] ?? "neutral"} className={className}>
      <span className={cn("size-1.5 rounded-full", GRADE_DOT[grade])} aria-hidden />
      {t(`viewer.grade.${grade}`)}
      {score !== undefined && <span className="tabular-nums opacity-80">· {Math.round(score)}</span>}
    </Badge>
  );
}

const STATUS_TONE: Record<ElementStatus, Tone> = { ok: "neutral", weak: "danger", fixed: "info", accepted: "success" };
export function StatusChip({ status }: { status: ElementStatus }) {
  const { t } = useTranslation();
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{t(`viewer.status.${status}`)}</Badge>;
}

export function WeakChip({
  code,
  severity = "warn",
  detail,
  count,
  muted,
}: {
  code: WeakCode;
  severity?: "warn" | "error";
  detail?: string;
  count?: number;
  muted?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <Badge tone={muted ? "neutral" : severity === "error" ? "danger" : "warning"} className={cn(muted && "line-through")}>
      {t(`viewer.weakCode.${code}`)}
      {detail && <span className="tabular-nums opacity-80">{detail}</span>}
      {count !== undefined && <span className="tabular-nums opacity-80">· {count}</span>}
    </Badge>
  );
}

export function LabelChip({ label }: { label: ElementLabel }) {
  const { t } = useTranslation();
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", labelColor(label).chip)}>
      {t(`viewer.label.${label}`, { defaultValue: label })}
    </span>
  );
}

export function OrderBadge({ label, order, className }: { label: ElementLabel; order: number; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded px-1 text-[11px] font-semibold tabular-nums",
        labelColor(label).badge,
        className,
      )}
    >
      {order}
    </span>
  );
}

/** Lỗi tải dữ liệu: câu dịch theo mã + nút thử lại. */
export function QueryError({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const { t } = useTranslation();
  const text = useErrorText();
  return (
    <div className={cn("flex flex-col items-center gap-3 px-6 py-10 text-center text-sm", className)} role="alert">
      <AlertTriangle className="size-5 text-danger" />
      <div>
        <p className="font-medium">{t("viewer.state.error")}</p>
        <p className="mt-1 text-xs text-muted-foreground">{text(error)}</p>
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCw />
          {t("viewer.state.retry")}
        </Button>
      )}
    </div>
  );
}

export function fmtBytes(n: number) {
  if (!n) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** Phím ←/→ không áp dụng khi đang gõ trong ô nhập, editor hay hộp thoại. */
export function isTypingTarget(target: EventTarget | null) {
  const el = target as HTMLElement | null;
  if (!el?.closest) return false;
  return !!el.closest("input, textarea, select, [contenteditable=true], .cm-editor, [role=dialog], [role=menu], [role=listbox]");
}
