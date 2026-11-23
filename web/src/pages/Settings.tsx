import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { PageHeader, useToastError } from "@/components/common";
import { Button, Input, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

/* ================================================================ Pipeline (lớp 4) */
// Chỉ vài mục người vận hành cần chỉnh (backend: EDITABLE trong app/domain/options.py).
// Prompt, luật chunk, tiêu chí trang dễ… cố định trong code để người dùng prod không chỉnh nhầm.
interface Opts {
  review: { chunk_warn_below: number };
  quality: { weak_confidence: number; auto_vlm_below: number };
}

/** Ngưỡng 0–1 nhập dạng % (0–100) cho dễ hiểu. */
function PercentInput({
  value,
  onChange,
  label,
  invalid,
}: {
  value: number;
  onChange: (v: number) => void;
  label: string;
  invalid?: boolean;
}) {
  return (
    <div className="relative w-24">
      <Input
        aria-label={label}
        aria-invalid={invalid || undefined}
        type="number"
        min={0}
        max={100}
        step={5}
        className={cn("pr-7 text-right tabular-nums shadow-none", invalid && "border-danger")}
        value={Math.round(value * 100)}
        onChange={(e) => onChange(Math.min(100, Math.max(0, Number(e.target.value))) / 100)}
      />
      <span className="pointer-events-none absolute inset-y-0 right-2.5 flex items-center text-sm text-muted-foreground">%</span>
    </div>
  );
}

function PipelineForm() {
  const { t } = useTranslation();
  const toastError = useToastError();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["pipeline"],
    queryFn: () => api.get<{ version: number; options: Opts; updated_by: string; updated_at: string }>("/settings/pipeline"),
  });
  const [opts, setOpts] = useState<Opts | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (q.data) setOpts(structuredClone(q.data.options));
  }, [q.data]);
  const dirty = useMemo(() => JSON.stringify(opts) !== JSON.stringify(q.data?.options), [opts, q.data]);
  if (!opts || !q.data) return <Skeleton className="h-96" />;

  const set = <S extends keyof Opts>(section: S, patch: Partial<Opts[S]>) =>
    setOpts({ ...opts, [section]: { ...opts[section], ...patch } });

  const save = async () => {
    setBusy(true);
    try {
      const r = await api.put<{ version: number }>("/settings/pipeline", { options: opts });
      toast.success(t("settings.pipelineSaved", { v: r.version }));
      qc.invalidateQueries({ queryKey: ["pipeline"] });
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(false);
    }
  };

  // AI đọc lại phải thấp hơn ngưỡng ⚠ (đọc lại trước, còn thấp mới gắn ⚠)
  const order = opts.quality.auto_vlm_below >= opts.quality.weak_confidence;
  const rows: { step?: string; label: string; value: number; onChange: (v: number) => void; invalid?: boolean }[] = [
    {
      step: t("settings.stepOcr"),
      label: t("settings.reread"),
      value: opts.quality.auto_vlm_below,
      onChange: (v) => set("quality", { auto_vlm_below: v }),
      invalid: order,
    },
    { label: t("settings.toReview"), value: opts.quality.weak_confidence, onChange: (v) => set("quality", { weak_confidence: v }) },
    {
      step: t("settings.stepChunk"),
      label: t("settings.toReview"),
      value: opts.review.chunk_warn_below,
      onChange: (v) => set("review", { chunk_warn_below: v }),
    },
  ];

  return (
    <div className="max-w-xl">
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="grid grid-cols-[4.5rem_minmax(0,1fr)_auto] sm:grid-cols-[6rem_minmax(0,1fr)_auto] items-center gap-x-3 border-b border-border bg-muted/40 px-4 py-2 text-xs text-muted-foreground">
          <span>{t("settings.colStep")}</span>
          <span>{t("settings.colAction")}</span>
          <span className="w-24 text-right">{t("settings.colBelow")}</span>
        </div>
        {rows.map((r, i) => (
          <div
            key={i}
            className={cn(
              "grid grid-cols-[4.5rem_minmax(0,1fr)_auto] sm:grid-cols-[6rem_minmax(0,1fr)_auto] items-center gap-x-3 px-4 py-2.5 text-sm",
              r.step && i > 0 && "border-t border-border",
            )}
          >
            <span className="font-medium">{r.step}</span>
            <span>{r.label}</span>
            <PercentInput label={`${r.step ?? rows[i - 1].step} · ${r.label}`} value={r.value} onChange={r.onChange} invalid={r.invalid} />
          </div>
        ))}
      </div>
      {order && <p className="mt-2 text-sm text-danger">{t("settings.orderError")}</p>}

      <div className="mt-4 flex justify-end">
        <span className="flex items-center gap-2">
          <Button variant="ghost" disabled={!dirty} onClick={() => setOpts(structuredClone(q.data.options))}>
            {t("common.reset")}
          </Button>
          <Button onClick={save} disabled={!dirty || order} loading={busy}>
            {t("common.save")}
          </Button>
        </span>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const { t } = useTranslation();
  return (
    <>
      <PageHeader title={t("settings.title")} subtitle={t("settings.subtitle")} />
      <PipelineForm />
    </>
  );
}
