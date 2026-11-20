import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, Gauge, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useToastError } from "@/components/common";
import { Badge, Button, Dialog, Skeleton, Tip } from "@/components/ui";
import { api } from "@/lib/api";
import type { DocQuality, PageScore, WeakCode } from "@/lib/v2types";
import { FixWeakDialog } from "./FixWeakDialog";
import { GradeChip, WeakChip, vk } from "./shared";

/** Thứ tự hiển thị chip điểm yếu. */
const CODE_ORDER: WeakCode[] = [
  "picture_no_desc",
  "missing_text",
  "reread",
  "blank_page",
  "ocr_weak",
  "low_confidence",
  "table_suspect",
];

/** Thanh 品質 dưới thanh trên của tab 検査 + banner 要確認. */
export function QualityBar({
  docId,
  quality,
  loading,
  canEdit,
  onGoPage,
  onShowWeak,
  onStartPolling,
}: {
  docId: string;
  quality?: DocQuality;
  loading: boolean;
  canEdit: boolean;
  onGoPage: (p: number) => void;
  onShowWeak: () => void;
  onStartPolling: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();
  const [fixOpen, setFixOpen] = useState(false);
  const [scoring, setScoring] = useState(false);
  const [scores, setScores] = useState<PageScore[] | null>(null);

  const open = quality?.weak_open ?? 0;
  const codes = CODE_ORDER.filter((c) => (quality?.counts[c] ?? 0) > 0);

  const fixWeak = async (prompt: string) => {
    try {
      const r = await api.post<{ queued: number }>(`/documents/${docId}/fix-weak`, { prompt });
      toast.success(t("viewer.quality.fixQueued", { n: r?.queued ?? open }));
      qc.invalidateQueries({ queryKey: vk.all(docId) });
      onStartPolling();
    } catch (e) {
      toastError(e);
    }
  };

  const score = async () => {
    setScoring(true);
    try {
      const r = await api.post<{ scored: PageScore[] }>(`/documents/${docId}/score`, {});
      setScores(r?.scored ?? []);
      qc.invalidateQueries({ queryKey: vk.quality(docId) });
    } catch (e) {
      toastError(e);
    } finally {
      setScoring(false);
    }
  };

  return (
    <>
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-card px-4 py-2">
        <span className="flex items-center gap-1.5 text-sm font-semibold">
          <Gauge className="size-4 text-muted-foreground" aria-hidden />
          {t("viewer.quality.label")}
        </span>
        {loading ? (
          <Skeleton className="h-5 w-64" />
        ) : quality ? (
          <>
            <GradeChip grade={quality.grade} score={quality.score} />
            {quality.worst_page && (
              <Tip content={t("viewer.quality.worstTip")}>
                <button
                  type="button"
                  onClick={() => onGoPage(quality.worst_page!.page)}
                  className="inline-flex cursor-pointer items-center gap-0.5 rounded-md px-1.5 py-0.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  {t("viewer.quality.worst", { page: quality.worst_page.page })}
                  <ChevronRight className="size-3.5" aria-hidden />
                </button>
              </Tip>
            )}
            {codes.length > 0 && <span className="mx-1 h-4 w-px bg-border" aria-hidden />}
            {codes.map((c) => (
              <button key={c} type="button" onClick={onShowWeak} className="cursor-pointer rounded-full hover:brightness-95">
                <WeakChip code={c} count={quality.counts[c]} />
              </button>
            ))}
          </>
        ) : null}
        <div className="flex-1" />
        {canEdit && quality && (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="soft" size="sm" disabled={open === 0} onClick={() => setFixOpen(true)}>
              <Wand2 />
              {t("viewer.quality.fixWeak", { n: open })}
            </Button>
            <Button variant="outline" size="sm" loading={scoring} onClick={score}>
              {!scoring && <Sparkles />}
              {t("viewer.quality.score")}
            </Button>
          </div>
        )}
      </div>

      {open > 0 && (
        <div
          role="status"
          className="flex shrink-0 items-start gap-2.5 border-b border-warning/30 bg-warning-soft px-4 py-2 text-sm"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <p className="min-w-0 flex-1 leading-relaxed">{t("viewer.quality.banner", { n: open })}</p>
          <Button variant="link" size="sm" className="h-auto shrink-0 py-0.5" onClick={onShowWeak}>
            {t("viewer.quality.bannerShow")}
          </Button>
        </div>
      )}

      <FixWeakDialog docId={docId} weakOpen={open} open={fixOpen} onOpenChange={setFixOpen} onRun={fixWeak} />

      <Dialog
        open={scores !== null}
        onOpenChange={(o) => !o && setScores(null)}
        title={t("viewer.quality.scoreTitle")}
        description={t("viewer.quality.scoreHint")}
        className="max-w-xl"
      >
        {scores?.length ? (
          <ul className="divide-y divide-border">
            {scores.map((s) => (
              <li key={s.page} className="flex items-start gap-3 py-3">
                <Badge tone="neutral" className="mt-0.5 tabular-nums">
                  {t("viewer.page.short", { page: s.page })}
                </Badge>
                <div className="min-w-0 flex-1">
                  <GradeChip grade={s.grade} score={s.score} />
                  {s.comment && <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{s.comment}</p>}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setScores(null);
                    onGoPage(s.page);
                  }}
                >
                  {t("viewer.quality.scoreOpen")}
                  <ChevronRight />
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">{t("viewer.quality.scoreEmpty")}</p>
        )}
      </Dialog>
    </>
  );
}
