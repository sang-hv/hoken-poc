import { AlertTriangle, CheckCircle2, CircleDashed, Clock, Loader2, Pause, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { DocStatus, JobStatus, PageStatus } from "@/lib/types";
import { Badge, type Tone } from "./ui";

const DOC_TONE: Record<DocStatus, Tone> = {
  processing: "info",
  stitching: "info",
  ocr_review: "warning",
  ready_for_chunking: "primary",
  chunking: "violet",
  chunk_review: "warning",
  indexing: "violet",
  indexed: "success",
  failed: "danger",
};

const RUNNING_DOC = new Set<DocStatus>(["processing", "stitching", "chunking", "indexing"]);

export function DocStatusBadge({ status }: { status: DocStatus }) {
  const { t } = useTranslation();
  return (
    <Badge tone={DOC_TONE[status]}>
      {RUNNING_DOC.has(status) ? (
        <Loader2 className="animate-spin" />
      ) : status === "indexed" ? (
        <CheckCircle2 />
      ) : status === "failed" ? (
        <XCircle />
      ) : (
        <span className="size-1.5 rounded-full bg-current" />
      )}
      {t(`docStatus.${status}`)}
    </Badge>
  );
}

export const PAGE_TONE: Record<PageStatus, Tone> = {
  queued: "neutral",
  docling: "info",
  routed: "info",
  cu: "violet",
  ready: "info",
  review: "warning",
  approved: "success",
  failed: "danger",
};

export function PageStatusBadge({ status }: { status: PageStatus }) {
  const { t } = useTranslation();
  return <Badge tone={PAGE_TONE[status]}>{t(`pageStatus.${status}`)}</Badge>;
}

const JOB: Record<JobStatus, { tone: Tone; icon: React.ReactNode }> = {
  queued: { tone: "neutral", icon: <Clock /> },
  running: { tone: "info", icon: <Loader2 className="animate-spin" /> },
  succeeded: { tone: "success", icon: <CheckCircle2 /> },
  failed: { tone: "danger", icon: <XCircle /> },
  cancelled: { tone: "neutral", icon: <Pause /> },
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const { t } = useTranslation();
  return (
    <Badge tone={JOB[status].tone}>
      {JOB[status].icon}
      {t(`jobStatus.${status}`)}
    </Badge>
  );
}

const GRADE_TONE: Record<string, Tone> = {
  poor: "danger",
  fair: "warning",
  good: "info",
  excellent: "success",
  unspecified: "neutral",
};

export function GradeBadge({ grade }: { grade: string }) {
  const { t } = useTranslation();
  const g = (grade || "unspecified").toLowerCase();
  return <Badge tone={GRADE_TONE[g] ?? "neutral"}>{t(`grades.${g}`, { defaultValue: g })}</Badge>;
}

export function RouteBadge({ route }: { route: "easy" | "hard" | null }) {
  const { t } = useTranslation();
  if (!route) return <Badge tone="neutral"><CircleDashed />—</Badge>;
  return route === "easy" ? (
    <Badge tone="success">{t("route.easy")}</Badge>
  ) : (
    <Badge tone="violet">
      <AlertTriangle />
      {t("route.hard")}
    </Badge>
  );
}

export function ScoreBar({ value, label }: { value: number | null; label: string }) {
  const v = value ?? null;
  const color = v === null ? "bg-muted" : v < 0.5 ? "bg-danger" : v < 0.8 ? "bg-warning" : v < 0.9 ? "bg-info" : "bg-success";
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-14 shrink-0 text-muted-foreground">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${(v ?? 0) * 100}%` }} />
      </div>
      <span className="w-9 text-right font-mono tabular-nums">{v === null ? "—" : v.toFixed(2)}</span>
    </div>
  );
}

export function ConfidenceBadge({ value }: { value: number }) {
  const tone: Tone = value < 0.5 ? "danger" : value < 0.7 ? "warning" : value < 0.9 ? "info" : "success";
  return (
    <Badge tone={tone} className="font-mono tabular-nums">
      {Math.round(value * 100)}%
    </Badge>
  );
}
