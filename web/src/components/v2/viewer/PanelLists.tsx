/** Các tab phụ của panel 検査: チャンク (chunk của trang) · 弱点 (toàn tài liệu) · 修正履歴 (lịch sử trang). */
import { CheckCircle2, History, Layers, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge, EmptyState, Skeleton } from "@/components/ui";
import type { HistoryItem, WeakItem } from "@/lib/v2types";
import { cn, fmtDateTime } from "@/lib/utils";
import { OrderBadge, QueryError, StatusChip, WeakChip, useHistory, usePageChunks, useWeak } from "./shared";

function ListSkeleton() {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: 4 }, (_, i) => (
        <Skeleton key={i} className="h-20" />
      ))}
    </div>
  );
}

export function ChunksList({ docId, page }: { docId: string; page: number }) {
  const { t } = useTranslation();
  const q = usePageChunks(docId, page);
  if (q.isLoading) return <ListSkeleton />;
  if (q.isError) return <QueryError error={q.error} onRetry={() => q.refetch()} />;
  const list = (q.data ?? []).slice().sort((a, b) => a.seq - b.seq);
  if (!list.length) return <EmptyState icon={<Layers />} title={t("viewer.chunks.empty")} hint={t("viewer.chunks.emptyHint")} />;
  return (
    <ul className="space-y-2 p-3">
      {list.map((c) => (
        <li key={c.id} className="rounded-lg border border-border bg-background/60 p-3">
          <div className="flex items-start gap-2">
            <p className="min-w-0 flex-1 text-sm font-semibold leading-snug">{c.title || t("viewer.chunks.untitled")}</p>
            {c.item_code && (
              <Badge tone="primary" className="shrink-0 font-mono">
                {c.item_code}
              </Badge>
            )}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 text-[11px] tabular-nums text-muted-foreground">
            <span>{t("viewer.chunks.tokens", { n: Math.max(1, Math.round(c.text.length / 2)).toLocaleString() })}</span>
            <span>{t("viewer.chunks.pages", { from: c.page_from, to: c.page_to })}</span>
          </div>
          <p className="mt-2 line-clamp-6 whitespace-pre-line break-words text-[13px] leading-relaxed text-foreground/90">{c.text}</p>
        </li>
      ))}
    </ul>
  );
}

export function WeakList({ docId, onOpen }: { docId: string; onOpen: (page: number, eid: string) => void }) {
  const { t } = useTranslation();
  const q = useWeak(docId);
  if (q.isLoading) return <ListSkeleton />;
  if (q.isError) return <QueryError error={q.error} onRetry={() => q.refetch()} />;
  const items = q.data ?? [];
  if (!items.length)
    return <EmptyState icon={<ShieldCheck />} title={t("viewer.weakList.empty")} hint={t("viewer.weakList.emptyHint")} />;

  const groups = new Map<number, WeakItem[]>();
  for (const w of items) groups.set(w.page, [...(groups.get(w.page) ?? []), w]);
  const pages = [...groups.keys()].sort((a, b) => a - b);

  return (
    <div className="space-y-4 p-3">
      {pages.map((p) => {
        const rows = groups.get(p)!.slice().sort((a, b) => a.order - b.order || a.code.localeCompare(b.code));
        const open = rows.filter((r) => r.status === "weak").length;
        return (
          <section key={p}>
            <h3 className="mb-1.5 flex items-center gap-2 px-1 text-xs font-semibold">
              <span className="tabular-nums">{t("viewer.page.short", { page: p })}</span>
              {open > 0 ? (
                <span className="font-medium text-danger">{t("viewer.weakList.open", { n: open })}</span>
              ) : (
                <span className="flex items-center gap-1 font-medium text-success">
                  <CheckCircle2 className="size-3.5" aria-hidden />
                  {t("viewer.weakList.resolved")}
                </span>
              )}
            </h3>
            <ul className="space-y-1">
              {rows.map((w, i) => {
                const resolved = w.status !== "weak";
                return (
                  <li key={`${w.element_id}:${w.code}:${i}`}>
                    <button
                      type="button"
                      onClick={() => onOpen(w.page, w.element_id)}
                      className={cn(
                        "flex w-full cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 text-left transition hover:bg-accent",
                        resolved ? "border-transparent opacity-60" : "border-border",
                      )}
                    >
                      <OrderBadge label={w.label} order={w.order} className="mt-0.5" />
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-1.5">
                          <span className="text-xs font-semibold">{t(`viewer.label.${w.label}`, { defaultValue: w.label })}</span>
                          <WeakChip code={w.code} severity={w.severity} muted={resolved} />
                          {resolved && <StatusChip status={w.status} />}
                        </span>
                        {w.preview && (
                          <span className="mt-0.5 line-clamp-2 break-words text-xs text-muted-foreground">{w.preview}</span>
                        )}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

const KIND_TONE: Record<HistoryItem["kind"], "neutral" | "info" | "violet" | "success"> = {
  page_version: "neutral",
  element_edit: "info",
  element_reread: "violet",
  element_accept: "success",
};

export function HistoryList({ docId, page, onOpen }: { docId: string; page: number; onOpen: (eid: string) => void }) {
  const { t } = useTranslation();
  const q = useHistory(docId, page);
  if (q.isLoading) return <ListSkeleton />;
  if (q.isError) return <QueryError error={q.error} onRetry={() => q.refetch()} />;
  const items = (q.data ?? []).slice().sort((a, b) => b.at.localeCompare(a.at));
  if (!items.length) return <EmptyState icon={<History />} title={t("viewer.history.empty")} />;
  return (
    <ol className="relative space-y-3 p-4 before:absolute before:bottom-6 before:left-[1.3rem] before:top-6 before:w-px before:bg-border">
      {items.map((h, i) => (
        <li key={`${h.at}:${i}`} className="relative flex gap-3">
          <span className="relative z-10 mt-1.5 size-2.5 shrink-0 rounded-full border-2 border-card bg-muted-foreground/60 ring-1 ring-border" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone={KIND_TONE[h.kind] ?? "neutral"}>{t(`viewer.history.kind.${h.kind}`, { defaultValue: h.kind })}</Badge>
              {h.element_id && (
                <button
                  type="button"
                  onClick={() => onOpen(h.element_id)}
                  className="cursor-pointer rounded font-mono text-[11px] text-primary hover:underline"
                >
                  {h.element_id}
                </button>
              )}
            </div>
            {h.summary && <p className="mt-1 break-words text-[13px]">{h.summary}</p>}
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {h.by || "—"} · {fmtDateTime(h.at)}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
