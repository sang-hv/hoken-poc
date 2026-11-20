import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Info, RefreshCw, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Markdown, useToastError } from "@/components/common";
import { Button, EmptyState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { Insights } from "@/lib/v2types";
import { fmtDateTime } from "@/lib/utils";
import { QueryError, useInsights, vk } from "./shared";

/** インサイト: tóm tắt + ý chính do LLM tạo. 404 no_insights → trạng thái rỗng với nút tạo. */
export function InsightsTab({ docId, canEdit }: { docId: string; canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();
  const insights = useInsights(docId);
  const gen = useMutation({
    mutationFn: () => api.post<Insights>(`/documents/${docId}/insights`),
    onSuccess: (data) => {
      qc.setQueryData(vk.insights(docId), data);
      toast.success(t("viewer.insights.done"));
    },
    onError: toastError,
  });

  const d = insights.data;
  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-card">
      <div className="mx-auto max-w-3xl px-6 py-8 lg:px-10">
        {insights.isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-24" />
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-40" />
          </div>
        ) : insights.isError ? (
          <QueryError error={insights.error} onRetry={() => insights.refetch()} />
        ) : !d ? (
          <EmptyState
            icon={<Sparkles />}
            title={t("viewer.insights.emptyTitle")}
            hint={canEdit ? t("viewer.insights.emptyHint") : t("viewer.state.readOnly")}
            action={
              canEdit && (
                <Button loading={gen.isPending} onClick={() => gen.mutate()}>
                  {!gen.isPending && <Sparkles />}
                  {t("viewer.insights.generate")}
                </Button>
              )
            }
          />
        ) : (
          <div className="space-y-8">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">
                {t("viewer.insights.generatedAt", { at: fmtDateTime(d.generated_at) })}
              </p>
              {canEdit && (
                <Button variant="outline" size="sm" loading={gen.isPending} onClick={() => gen.mutate()}>
                  {!gen.isPending && <RefreshCw />}
                  {t("viewer.insights.regenerate")}
                </Button>
              )}
            </div>
            <section>
              <h2 className="mb-3 flex items-center gap-2 text-base font-semibold">
                <Sparkles className="size-4 text-violet" aria-hidden />
                {t("viewer.insights.summary")}
              </h2>
              <Markdown text={d.summary} className="text-[15px] leading-[1.9]" />
            </section>
            {d.key_points.length > 0 && (
              <section>
                <h2 className="mb-3 text-base font-semibold">{t("viewer.insights.keyPoints")}</h2>
                <ol className="space-y-2.5">
                  {d.key_points.map((k, i) => (
                    <li key={i} className="flex gap-3 rounded-lg border border-border bg-background/60 px-4 py-3 text-sm leading-relaxed">
                      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-violet-soft text-xs font-semibold text-violet">
                        {i + 1}
                      </span>
                      <span className="min-w-0 pt-0.5">{k}</span>
                    </li>
                  ))}
                </ol>
              </section>
            )}
            <p className="flex items-start gap-2 rounded-lg bg-muted px-4 py-3 text-xs text-muted-foreground">
              <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {t("viewer.insights.aiNote")}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
