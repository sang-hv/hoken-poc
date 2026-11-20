import { FileText } from "lucide-react";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Markdown } from "@/components/common";
import { EmptyState, Skeleton } from "@/components/ui";
import type { DocInfo } from "@/lib/v2types";
import { InfoPanel } from "./InfoPanel";
import { QueryError, usePageText } from "./shared";

/** テキスト: Markdown đã xử lý của mọi trang, nhãn "p.N" ở ranh giới trang. */
export function TextTab({
  docId,
  info,
  infoLoading,
  page,
  onShowInsights,
}: {
  docId: string;
  info?: DocInfo;
  infoLoading: boolean;
  page: number;
  onShowInsights: () => void;
}) {
  const { t } = useTranslation();
  const text = usePageText(docId);
  const scroller = useRef<HTMLDivElement>(null);
  const scrolled = useRef(false);

  // Mở tab với ?page=N → cuộn tới trang đó một lần.
  useEffect(() => {
    if (scrolled.current || !text.data?.length || page <= 1) return;
    scrolled.current = true;
    scroller.current?.querySelector(`[data-page="${page}"]`)?.scrollIntoView({ block: "start" });
  }, [text.data, page]);

  return (
    <div className="flex min-h-0 flex-1">
      <div ref={scroller} className="min-h-0 min-w-0 flex-1 overflow-y-auto bg-card">
        <div className="mx-auto max-w-3xl px-6 py-8 lg:px-10">
          {text.isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 10 }, (_, i) => (
                <Skeleton key={i} className={i % 4 === 0 ? "h-6 w-1/2" : "h-4"} />
              ))}
            </div>
          ) : text.isError ? (
            <QueryError error={text.error} onRetry={() => text.refetch()} />
          ) : !text.data?.length ? (
            <EmptyState icon={<FileText />} title={t("viewer.text.empty")} hint={t("viewer.text.emptyHint")} />
          ) : (
            text.data.map((p) => (
              <article key={p.page} data-page={p.page} className="scroll-mt-4">
                {p.markdown.trim() ? (
                  <Markdown text={p.markdown} className="text-[15px] leading-[1.9]" />
                ) : (
                  <p className="py-4 text-sm italic text-muted-foreground">{t("viewer.text.emptyPage")}</p>
                )}
                <div className="my-6 flex items-center gap-3" aria-hidden>
                  <span className="h-px flex-1 bg-border" />
                  <span className="text-[11px] tabular-nums text-muted-foreground">{t("viewer.page.short", { page: p.page })}</span>
                </div>
              </article>
            ))
          )}
        </div>
      </div>
      <InfoPanel docId={docId} info={info} loading={infoLoading} onShowInsights={onShowInsights} />
    </div>
  );
}
