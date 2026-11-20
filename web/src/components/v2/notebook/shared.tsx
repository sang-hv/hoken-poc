import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Badge, type Tone } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { NotebookDetail, NotebookSource, QualityGrade } from "@/lib/v2types";

/** Query key dùng chung cho sổ tay (danh sách / chi tiết). */
export const nbKeys = {
  list: ["notebooks"] as const,
  detail: (id: string) => ["notebook", id] as const,
};

export const isSettled = (s: NotebookSource) => s.stage === "done" || s.stage === "failed";
export const isReady = (s: NotebookSource) => s.stage === "done";

/** Chi tiết sổ tay; poll 2 giây/lần khi còn nguồn đang xử lý. */
export function useNotebook(id: string) {
  return useQuery({
    queryKey: nbKeys.detail(id),
    queryFn: () => api.get<NotebookDetail>(`/notebooks/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data?.sources.some((s) => !isSettled(s)) ? 2000 : false),
  });
}

export const gradeTone: Record<QualityGrade, Tone> = { good: "success", fair: "warning", poor: "danger" };

export function GradeChip({ grade, score, className }: { grade: QualityGrade; score: number; className?: string }) {
  const { t } = useTranslation();
  return (
    <Badge tone={gradeTone[grade]} className={className} title={t("nb.sources.quality", { score: Math.round(score) })}>
      {t(`nb.grade.${grade}`)}
      <span className="tabular-nums opacity-80">{Math.round(score)}</span>
    </Badge>
  );
}

/** Viên "使用中 2 / 2 ソース". */
export function UsagePill({ on, total, className }: { on: number; total: number; className?: string }) {
  const { t } = useTranslation();
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-border bg-card px-2.5 py-0.5 text-xs font-medium tabular-nums",
        on === 0 ? "text-muted-foreground" : "text-foreground",
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", on === 0 ? "bg-muted-foreground" : "bg-success")} aria-hidden />
      {t("nb.top.usage", { on, total })}
    </span>
  );
}

/** Khung một cột: tiêu đề cố định + thân cuộn. */
export function Column({
  title,
  count,
  actions,
  children,
  footer,
  className,
  bodyRef,
}: {
  title: React.ReactNode;
  count?: number;
  actions?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  bodyRef?: React.Ref<HTMLDivElement>;
}) {
  return (
    <section className={cn("flex min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border border-border bg-card shadow-card", className)}>
      <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-border px-3.5">
        <h2 className="flex min-w-0 items-center gap-1.5 text-sm font-semibold">
          <span className="truncate">{title}</span>
          {count !== undefined && <span className="tabular-nums text-muted-foreground">{count}</span>}
        </h2>
        {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
      </header>
      <div ref={bodyRef} className="min-h-0 flex-1 overflow-y-auto" aria-live={bodyRef ? "polite" : undefined}>
        {children}
      </div>
      {footer}
    </section>
  );
}
