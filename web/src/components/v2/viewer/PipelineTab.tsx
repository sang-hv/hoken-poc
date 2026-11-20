import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  FileText,
  Layers,
  ListChecks,
  Loader2,
  MessagesSquare,
  Pencil,
  RefreshCw,
  Route,
  ScanText,
  Sparkles,
  UserCheck,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useToastError } from "@/components/common";
import { LiveLog } from "@/components/LiveLog";
import { DocStatusBadge } from "@/components/status";
import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Doc, DocStatus, JobEvent, Page } from "@/lib/types";
import type { DocQuality } from "@/lib/v2types";
import { cn } from "@/lib/utils";
import { RenameDialog } from "@/pages/Documents";
import { ReviewGate, reviewMode, reviewStage } from "./ReviewGate";
import { type ViewerTab, vk } from "./shared";

const ORDER: DocStatus[] = [
  "processing",
  "stitching",
  "ocr_review",
  "ready_for_chunking",
  "chunking",
  "chunk_review",
  "indexing",
  "indexed",
];

type StepState = "pending" | "running" | "done" | "action" | "failed";

/** Các bước pipeline suy ra từ trạng thái tài liệu + `doc.stats` (đếm trang theo trạng thái) — không cần tải
 *  danh sách trang, nên tài liệu nhiều trang vẫn nhẹ khi làm mới liên tục. */
function useSteps(doc: Doc | undefined) {
  return useMemo(() => {
    if (!doc) return [];
    const at = ORDER.indexOf(doc.status);
    const by = (s: string) => doc.stats[s] ?? 0;
    const total = doc.page_to - doc.page_from + 1;
    const hard = doc.stats.hard ?? 0;
    const pre = by("queued") + by("docling");
    const s = (cond: boolean, running: boolean, action = false): StepState =>
      cond ? "done" : running ? (action ? "action" : "running") : "pending";
    const doclingDone = total - pre;
    // auto: bước duyệt tự qua; warn: chỉ chờ người khi pipeline dừng vì cảnh báo; manual: luôn chờ
    const stage = reviewStage(doc);
    const auto = reviewMode(doc) === "auto";
    const autoMeta = (m?: string) => (auto ? "auto" : m);
    return [
      { key: "docling", icon: <ScanText />, state: s(pre === 0, true), meta: `${doclingDone}/${total}` },
      { key: "route", icon: <Route />, state: s(pre === 0 && by("routed") === 0, doclingDone > 0), meta: `${hard} → CU` },
      {
        key: "cu",
        icon: <Sparkles />,
        state: s(at >= 1 && by("cu") === 0 && pre === 0, by("cu") > 0),
        meta: doc.stats.cu_skipped ? `${hard - doc.stats.cu_skipped}/${hard} · ${doc.stats.cu_skipped} skip` : `${hard}`,
      },
      { key: "stitch", icon: <Layers />, state: s(at >= 2, doc.status === "stitching") },
      {
        key: "review",
        icon: <UserCheck />,
        state: s(at >= 3, at === 2, stage === "ocr"),
        meta: autoMeta(`${by("approved")}/${total}`),
      },
      { key: "chunk", icon: <Layers />, state: s(at >= 5, at === 3 || at === 4, at === 3 && stage === "ocr") },
      {
        key: "chunkReview",
        icon: <ListChecks />,
        state: s(at >= 6, at === 5, stage === "chunk"),
        meta: autoMeta(doc.stats.chunks ? `${doc.stats.chunks_approved ?? 0}/${doc.stats.chunks}` : undefined),
      },
      { key: "index", icon: <FileText />, state: s(at >= 7, at === 6) },
    ] as { key: string; icon: React.ReactNode; state: StepState; meta?: string }[];
  }, [doc]);
}

const STEP_BAR: Record<StepState, string> = {
  done: "bg-success",
  running: "bg-info animate-pulse",
  action: "bg-warning",
  pending: "bg-muted",
  failed: "bg-danger",
};
const STEP_ICON: Record<StepState, string> = {
  done: "text-success",
  running: "text-info",
  action: "text-warning",
  pending: "text-muted-foreground",
  failed: "text-danger",
};

/** Stepper gọn: ≥1400px một hàng 8 bước, md–1400px 2 hàng × 4; màn hẹp chỉ còn thanh 8 đoạn + bước hiện tại. */
function Stepper({ steps }: { steps: ReturnType<typeof useSteps> }) {
  const { t } = useTranslation();
  const label: Record<StepState, string> = {
    pending: t("detail.stepPending"),
    running: t("detail.stepRunning"),
    done: t("detail.stepDone"),
    action: t("detail.stepAction"),
    failed: t("jobStatus.failed"),
  };
  const meta = (m?: string) => (m === "auto" ? t("detail.autoStep") : m);
  const status = (s: (typeof steps)[number]) => `${label[s.state]}${s.meta ? ` · ${meta(s.meta)}` : ""}`;
  const icon = (s: (typeof steps)[number]) =>
    s.state === "done" ? <Check /> : s.state === "running" ? <Loader2 className="animate-spin" /> : s.icon;
  let cur = steps.findIndex((s) => s.state === "action" || s.state === "running" || s.state === "failed");
  if (cur < 0) cur = steps.every((s) => s.state === "done") ? steps.length - 1 : Math.max(0, steps.findIndex((s) => s.state === "pending"));
  const current = steps[cur];
  return (
    <>
      <ol className="hidden grid-cols-4 gap-x-3 gap-y-4 md:grid min-[1400px]:grid-cols-8 min-[1400px]:gap-x-2">
        {steps.map((s) => (
          <li key={s.key} className="flex min-w-0 flex-col gap-1.5" aria-current={s === current ? "step" : undefined}>
            <span className={cn("h-1.5 rounded-full", STEP_BAR[s.state])} />
            <span
              className={cn(
                "flex min-w-0 items-start gap-1.5 break-words text-xs leading-tight [&_svg]:mt-px [&_svg]:size-3.5 [&_svg]:shrink-0",
                s.state === "pending" ? "text-muted-foreground" : "font-medium",
                s.state === "action" && "font-semibold",
              )}
            >
              <span className={STEP_ICON[s.state]}>{icon(s)}</span>
              <span className="min-w-0">{t(`steps.${s.key}`)}</span>
            </span>
            <span className={cn("text-[11px]", s.state === "action" ? "text-warning" : "text-muted-foreground")}>
              {status(s)}
            </span>
          </li>
        ))}
      </ol>
      {current && (
        <div className="flex flex-col gap-2 md:hidden">
          <div className="flex gap-1">
            {steps.map((s) => (
              <span key={s.key} className={cn("h-1.5 flex-1 rounded-full", STEP_BAR[s.state])} />
            ))}
          </div>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm">
            <span className="font-mono text-xs text-muted-foreground">
              {cur + 1}/{steps.length}
            </span>
            <span className={cn("flex items-center gap-1.5 font-semibold [&_svg]:size-4", STEP_ICON[current.state])}>
              {icon(current)}
              <span className="text-foreground">{t(`steps.${current.key}`)}</span>
            </span>
            <span className={cn("text-xs", current.state === "action" ? "text-warning" : "text-muted-foreground")}>
              {status(current)}
            </span>
          </p>
        </div>
      )}
    </>
  );
}

/** Tab パイプライン của màn chi tiết tài liệu: tiến độ các bước, nút thao tác, live log ở dưới.
 *  Live log dùng chung kết nối SSE của màn (DocumentViewer) — mỗi màn chỉ một kết nối. */
export function PipelineTab({
  docId,
  onTab,
  events,
  connected,
  maxEvents,
}: {
  docId: string;
  onTab: (t: ViewerTab) => void;
  events: JobEvent[];
  connected: boolean;
  maxEvents: number;
}) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toastError = useToastError();
  const [renaming, setRenaming] = useState(false);
  const doc = useQuery({ queryKey: ["document", docId], queryFn: () => api.get<Doc>(`/documents/${docId}`) });
  const steps = useSteps(doc.data);
  // Chất lượng sau pipeline + số cảnh báo chưa xử lý (chỉ có khi đã qua bước nối trang)
  const quality = useQuery({
    queryKey: vk.quality(docId),
    queryFn: () => api.get<DocQuality>(`/documents/${docId}/quality`),
    enabled: !!doc.data && !["processing", "stitching"].includes(doc.data.status),
    retry: false,
  });

  const action = async (name: string) => {
    try {
      await api.post(`/documents/${docId}/actions/${name}`);
      toast.success(t("common.saved"));
      qc.invalidateQueries({ queryKey: ["document", docId] });
    } catch (e) {
      toastError(e);
    }
  };

  if (doc.isLoading || !doc.data)
    return (
      <div className="flex flex-col gap-4 p-4 lg:p-6">
        <Skeleton className="h-36" />
        <Skeleton className="h-80" />
      </div>
    );
  const d = doc.data;
  const total = d.page_to - d.page_from + 1;
  const failed = d.stats.failed ?? 0;
  const q = quality.data;
  const editor = can("reviewer");

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-[1400px] flex-col gap-4 p-4 lg:p-6">
        <Card>
          <CardContent className="flex flex-col gap-4 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex min-w-0 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-semibold">{t("detail.pipeline")}</p>
                  <DocStatusBadge status={d.status} />
                  <Badge tone={reviewMode(d) === "manual" ? "neutral" : "primary"}>
                    {t(`detail.mode.${reviewMode(d)}`)}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  {t(`kinds.${d.kind}`, { defaultValue: d.kind })} ·{" "}
                  {t("documents.bookPages", { from: d.book_page_start, to: d.book_page_start + total - 1 })} · PDF p
                  {d.page_from}–{d.page_to} / {d.total_pdf_pages} · {t("jobs.configVersion", { v: d.config_version })}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {editor && (
                  <Button variant="ghost" size="sm" onClick={() => setRenaming(true)}>
                    <Pencil />
                    {t("common.rename")}
                  </Button>
                )}
                {editor && failed > 0 && (
                  <Button variant="outline" size="sm" onClick={() => action("retry_failed")}>
                    <RefreshCw />
                    {t("detail.retryFailed")}
                  </Button>
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 text-xs">
              {(d.stats.hard ?? 0) > 0 && <Badge tone="violet">{t("detail.hardPages", { n: d.stats.hard })}</Badge>}
              {(d.stats.cu_skipped ?? 0) > 0 && (
                <Badge tone="warning">{t("detail.cuSkipped", { n: d.stats.cu_skipped })}</Badge>
              )}
              {failed > 0 && (
                <Badge tone="danger">
                  {t("pageStatus.failed")}: {failed}
                </Badge>
              )}
              {q && (
                <Badge tone={q.grade === "good" ? "success" : q.grade === "fair" ? "warning" : "danger"}>
                  {t(`viewer.grade.${q.grade}`)} · {q.score}
                </Badge>
              )}
              {q && q.weak_open > 0 && (
                <button type="button" onClick={() => onTab("inspect")} className="cursor-pointer">
                  <Badge tone="warning">
                    <AlertTriangle />
                    {t("detail.weakOpen", { n: q.weak_open })}
                  </Badge>
                </button>
              )}
            </div>

            <Stepper steps={steps} />

            <ReviewGate doc={d} canEdit={editor} variant="card" onTab={onTab} />
            {d.status === "indexed" && (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-success-soft px-3 py-2 text-sm text-success">
                <span className="flex items-center gap-2 font-medium">
                  <Check className="size-4" />
                  {t("detail.readyToChat")}
                </span>
                {editor && (
                  <Button size="sm" variant="outline" onClick={() => nav("/test/chat")}>
                    <MessagesSquare />
                    {t("detail.openChat")}
                  </Button>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        <RenameDialog doc={renaming ? d : null} onClose={() => setRenaming(false)} />
        <LiveLog events={events} connected={connected} max={maxEvents} height="h-[min(60vh,560px)]" />
      </div>
    </div>
  );
}

/** /documents/:docId/review → tab 検査 ở trang đầu tiên đang chờ review (không còn thì về tab パイプライン). */
export function NextReviewRedirect() {
  const { docId = "" } = useParams();
  const pages = useQuery({ queryKey: ["pages", docId], queryFn: () => api.get<Page[]>(`/documents/${docId}/pages`) });
  if (pages.isError) return <Navigate to={`/documents/${docId}?tab=pipeline`} replace />;
  if (!pages.data) return <Skeleton className="h-80" />;
  const next = [...pages.data].sort((a, b) => a.page - b.page).find((p) => p.status === "review");
  return (
    <Navigate to={next ? `/documents/${docId}?tab=inspect&page=${next.page}` : `/documents/${docId}?tab=pipeline`} replace />
  );
}
