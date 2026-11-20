import { ChevronRight, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Skeleton } from "@/components/ui";
import type { DocInfo } from "@/lib/v2types";
import { fmtDateTime } from "@/lib/utils";
import { fmtBytes, useInsights } from "./shared";

function Row({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-2 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

/** Panel 情報 bên phải tab 原本 / テキスト. */
export function InfoPanel({ docId, info, loading, onShowInsights }: { docId: string; info?: DocInfo; loading: boolean; onShowInsights: () => void }) {
  const { t } = useTranslation();
  const insights = useInsights(docId);
  const lang = info?.language ?? "";
  return (
    <aside className="hidden w-80 shrink-0 overflow-y-auto border-l border-border bg-card lg:block">
      <section className="border-b border-border px-5 py-4">
        <h2 className="mb-2 text-sm font-semibold">{t("viewer.info.title")}</h2>
        {loading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-5" />
            ))}
          </div>
        ) : info ? (
          <dl>
            <Row label={t("viewer.info.type")}>{info.file_type === "image" ? t("viewer.info.typeImage") : t("viewer.info.typePdf")}</Row>
            <Row label={t("viewer.info.language")}>{lang ? t(`viewer.info.langs.${lang}`, { defaultValue: lang }) : "—"}</Row>
            <Row label={t("viewer.info.pages")}>
              <span className="tabular-nums">{info.pages}</span>
            </Row>
            <Row label={t("viewer.info.added")}>{fmtDateTime(info.created_at)}</Row>
            {info.created_by && <Row label={t("viewer.info.addedBy")}>{info.created_by}</Row>}
            <Row label={t("viewer.info.origin")}>
              {t("viewer.info.originUpload")} · <span className="tabular-nums">{fmtBytes(info.size_bytes)}</span>
            </Row>
            <Row label={t("viewer.info.context")}>{t("viewer.info.contextFull")}</Row>
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">—</p>
        )}
      </section>
      <section className="px-5 py-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold">
            <Sparkles className="size-4 text-violet" aria-hidden />
            {t("viewer.info.insights")}
          </h2>
          <button
            type="button"
            onClick={onShowInsights}
            className="inline-flex cursor-pointer items-center gap-0.5 text-xs font-medium text-primary hover:underline"
          >
            {t("viewer.info.show")}
            <ChevronRight className="size-3.5" aria-hidden />
          </button>
        </div>
        {insights.isLoading ? (
          <Skeleton className="h-16" />
        ) : insights.data ? (
          <p className="line-clamp-6 text-sm leading-relaxed text-muted-foreground">{insights.data.summary}</p>
        ) : (
          <p className="text-sm text-muted-foreground">{t("viewer.info.noInsights")}</p>
        )}
      </section>
    </aside>
  );
}
