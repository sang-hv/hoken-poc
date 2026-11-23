import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronRight, Circle, Loader2, MessagesSquare, Pencil, RefreshCw, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useToastError } from "@/components/common";
import { LiveLog } from "@/components/LiveLog";
import { DocStatusBadge } from "@/components/status";
import { Button, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Doc, DocStatus, JobEvent, Page } from "@/lib/types";
import type { DocQuality } from "@/lib/v2types";
import { cn } from "@/lib/utils";
import { RenameDialog } from "@/pages/Documents";
import { reviewMode, reviewStage } from "./ReviewGate";
import { Pane, PaneHeader, PaneRow } from "./pane";
import { RecognitionPanes } from "./RecognitionPanel";
import { GradeChip, type ViewerTab, vk } from "./shared";

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
    const steps = [
      { key: "docling", state: s(pre === 0, true), meta: `${doclingDone}/${total}` },
      { key: "route", state: s(pre === 0 && by("routed") === 0, doclingDone > 0), meta: `→ ${hard}` },
      {
        key: "cu",
        state: s(at >= 1 && by("cu") === 0 && pre === 0, by("cu") > 0),
        meta: doc.stats.cu_skipped ? `${hard - doc.stats.cu_skipped}/${hard} · ${doc.stats.cu_skipped} skip` : `${hard}`,
      },
      { key: "stitch", state: s(at >= 2, doc.status === "stitching") },
      {
        key: "review",
        state: s(at >= 3, at === 2, stage === "ocr"),
        meta: autoMeta(`${by("approved")}/${total}`),
      },
      { key: "chunk", state: s(at >= 5, at === 3 || at === 4, at === 3 && stage === "ocr") },
      {
        key: "chunkReview",
        state: s(at >= 6, at === 5, stage === "chunk"),
        meta: autoMeta(doc.stats.chunks ? `${doc.stats.chunks_approved ?? 0}/${doc.stats.chunks}` : undefined),
      },
      { key: "index", state: s(at >= 7, at === 6) },
    ] as { key: string; state: StepState; meta?: string }[];
    // Tài liệu lỗi: bước đầu tiên chưa xong là bước bị lỗi
    if (doc.status === "failed") {
      const i = steps.findIndex((x) => x.state !== "done");
      if (i >= 0) steps[i] = { ...steps[i], state: "failed" };
    }
    return steps;
  }, [doc]);
}

const STATE_ICON: Record<StepState, React.ReactNode> = {
  done: <Check className="size-4 text-muted-foreground" />,
  running: <Loader2 className="size-4 animate-spin text-info" />,
  action: <span className="block size-2.5 rounded-full bg-warning ring-4 ring-warning/20" />,
  pending: <Circle className="size-3.5 text-muted-foreground/50" />,
  failed: <X className="size-4 text-danger" />,
};

/** Vạch trên của ô bước: xong = xám đậm, chưa tới = xám nhạt; chỉ bước cần chú ý mới có màu. */
const STATE_BAR: Record<StepState, string> = {
  done: "bg-muted-foreground/50",
  running: "bg-info",
  action: "bg-warning",
  pending: "bg-border",
  failed: "bg-danger",
};

/** 8 bước dạng dải ngang (4 cột ở màn vừa, 8 cột ở màn rộng): tên bước · trạng thái + số liệu. */
function StepBar({ steps }: { steps: ReturnType<typeof useSteps> }) {
  const { t } = useTranslation();
  const label: Record<StepState, string> = {
    pending: t("detail.stepPending"),
    running: t("detail.stepRunning"),
    done: t("detail.stepDone"),
    action: t("detail.stepAction"),
    failed: t("jobStatus.failed"),
  };
  const meta = (m?: string) => (m === "auto" ? t("detail.autoStep") : m);
  const cur = steps.findIndex((s) => s.state === "action" || s.state === "running" || s.state === "failed");
  return (
    <ol aria-label={t("viewer.pipeline.title")} className="grid shrink-0 grid-cols-2 gap-px border-b border-border bg-border sm:grid-cols-4 xl:grid-cols-8">
      {steps.map((s, i) => (
        <li
          key={s.key}
          title={`${t(`steps.${s.key}`)} — ${t(`viewer.pipeline.stepDef.${s.key}`)}`}
          aria-current={i === cur ? "step" : undefined}
          className={cn("relative min-w-0 bg-card px-3 pb-2 pt-2.5", i === cur && "bg-accent")}
        >
          <span className={cn("absolute inset-x-0 top-0 h-0.5", STATE_BAR[s.state])} aria-hidden />
          <div className="flex items-center gap-1.5">
            <span className="flex size-4 shrink-0 items-center justify-center">{STATE_ICON[s.state]}</span>
            <span
              className={cn(
                "truncate text-sm",
                s.state === "pending" ? "text-muted-foreground" : i === cur && "font-medium",
              )}
            >
              {t(`viewer.pipeline.stepShort.${s.key}`, { defaultValue: t(`steps.${s.key}`) })}
            </span>
          </div>
          <div
            className={cn(
              "mt-0.5 truncate pl-5.5 text-xs tabular-nums",
              s.state === "action" ? "font-medium text-warning" : s.state === "failed" ? "text-danger" : "text-muted-foreground",
            )}
          >
            {label[s.state]}
            {s.meta ? ` · ${meta(s.meta)}` : ""}
          </div>
        </li>
      ))}
    </ol>
  );
}

function Row({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <PaneRow>
      <span className="w-24 shrink-0 text-muted-foreground">{label}</span>
      <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">{children}</span>
    </PaneRow>
  );
}

/** Tab パイプライン: trên = dải 8 bước (là tiêu đề của tab, không thêm thanh 工程); dưới = 3 ngăn rộng bằng nhau
 *  情報 | 認識結果 | 要対応ページ, cùng thanh tiêu đề và cùng chiều cao dòng (`pane.tsx`); chân = live log thu gọn được.
 *  Màn ≥ 1024px: vừa một màn, chỉ ngăn nào dài mới tự cuộn.
 *  Banner chờ review nằm dưới thanh trên (ReviewGate, render ở DocumentViewer). Live log dùng chung kết nối SSE. */
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
  const [logOpen, setLogOpen] = useState<boolean | null>(null);
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
      <div className="flex flex-1 flex-col gap-4 p-4">
        <Skeleton className="h-14" />
        <div className="grid flex-1 gap-4 lg:grid-cols-3">
          <Skeleton className="h-72" />
          <Skeleton className="hidden h-72 lg:block" />
          <Skeleton className="hidden h-72 lg:block" />
        </div>
      </div>
    );
  const d = doc.data;
  const total = d.page_to - d.page_from + 1;
  const failed = d.stats.failed ?? 0;
  const hard = d.stats.hard ?? 0;
  const cuSkipped = d.stats.cu_skipped ?? 0;
  const q = quality.data;
  const editor = can("reviewer");
  // Live log mở sẵn khi đang chạy; dừng chờ review / xong → thu gọn (người dùng tự mở lại được)
  const running = steps.some((s) => s.state === "running");
  const showLog = logOpen ?? running;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:overflow-hidden">
      <StepBar steps={steps} />
      {/* Dải thao tác — chỉ khi có việc: chạy lại trang lỗi, hoặc đã sẵn sàng để thử chat */}
      {(failed > 0 || d.status === "indexed") && (
        <div className="flex min-h-10 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-border bg-card px-5 py-1.5 text-sm">
          {failed > 0 ? (
            <>
              <X className="size-4 shrink-0 text-danger" aria-hidden />
              <span className="min-w-0 flex-1">{t("viewer.pipeline.failedNote", { count: failed })}</span>
              {editor && (
                <Button variant="outline" size="sm" className="h-7" onClick={() => action("retry_failed")}>
                  <RefreshCw />
                  {t("detail.retryFailed")}
                </Button>
              )}
            </>
          ) : (
            <>
              <Check className="size-4 shrink-0 text-success" aria-hidden />
              <span className="min-w-0 flex-1">{t("detail.readyToChat")}</span>
              {editor && (
                <Button size="sm" variant="outline" className="h-7" onClick={() => nav("/test/chat")}>
                  <MessagesSquare />
                  {t("detail.openChat")}
                </Button>
              )}
            </>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-px bg-border lg:min-h-0 lg:flex-1 lg:grid-cols-3">
        <Pane className="lg:min-h-0">
          <PaneHeader title={t("viewer.info.title")}>
            {editor && (
              <Button variant="ghost" size="sm" className="-mr-2 h-7 text-muted-foreground" onClick={() => setRenaming(true)}>
                <Pencil />
                {t("common.rename")}
              </Button>
            )}
          </PaneHeader>
          <div className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
            <Row label={t("viewer.pipeline.status")}>
              <DocStatusBadge status={d.status} />
            </Row>
            <Row label={t("viewer.pipeline.kind")}>{t(`kinds.${d.kind}`, { defaultValue: d.kind })}</Row>
            <Row label={t("viewer.pipeline.bookPages")}>
              <span className="tabular-nums">P{d.book_page_start}–{d.book_page_start + total - 1}</span>
            </Row>
            <Row label={t("viewer.pipeline.pdfPages")}>
              <span className="tabular-nums">
                p{d.page_from}–{d.page_to} / {d.total_pdf_pages}
              </span>
            </Row>
            {hard > 0 && (
              <Row label={t("viewer.pipeline.cu")}>
                <span className="tabular-nums">{t("viewer.pipeline.pages", { count: hard })}</span>
                {cuSkipped > 0 && <span className="text-warning">{t("viewer.pipeline.cuSkipped", { n: cuSkipped })}</span>}
              </Row>
            )}
            {q && (
              <Row label={t("viewer.pipeline.quality")}>
                <GradeChip grade={q.grade} score={q.score} />
                {q.weak_open > 0 && (
                  <button
                    type="button"
                    onClick={() => onTab("inspect")}
                    className="inline-flex cursor-pointer items-center gap-0.5 text-xs font-medium text-warning hover:underline"
                  >
                    {t("detail.weakOpen", { n: q.weak_open })}
                    <ChevronRight className="size-3.5" aria-hidden />
                  </button>
                )}
              </Row>
            )}
            {failed > 0 && (
              <Row label={t("viewer.pipeline.failed")}>
                <span className="tabular-nums text-danger">{t("viewer.pipeline.pages", { count: failed })}</span>
              </Row>
            )}
            <Row label={t("viewer.pipeline.config")}>
              <span className="tabular-nums">v{d.config_version}</span>
            </Row>
          </div>
        </Pane>
        <RecognitionPanes docId={docId} className="lg:min-h-0" />
      </div>

      <LiveLog
        bare
        className="shrink-0 border-t border-border"
        events={events}
        connected={connected}
        max={maxEvents}
        open={showLog}
        onOpenChange={setLogOpen}
        height="h-[min(32vh,320px)]"
      />

      <RenameDialog doc={renaming ? d : null} onClose={() => setRenaming(false)} />
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
