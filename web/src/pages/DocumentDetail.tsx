import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  ExternalLink,
  FileText,
  Layers,
  ListChecks,
  Pencil,
  Loader2,
  RefreshCw,
  Route,
  ScanSearch,
  ScanText,
  Sparkles,
  UserCheck,
} from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { PageHeader, useToastError } from "@/components/common";
import { LiveLog } from "@/components/LiveLog";
import { RenameDialog } from "./Documents";
import { DocStatusBadge, GradeBadge, JobStatusBadge, PAGE_TONE, PageStatusBadge, RouteBadge } from "@/components/status";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Select,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Tip,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useEventStream } from "@/lib/sse";
import type { Doc, DocStatus, Job, JobEvent, Page } from "@/lib/types";
import type { DocQuality } from "@/lib/v2types";
import { cn, fmtDuration, fmtRelative } from "@/lib/utils";

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

function useSteps(doc: Doc | undefined, pages: Page[] | undefined) {
  return useMemo(() => {
    if (!doc || !pages) return [];
    const at = ORDER.indexOf(doc.status);
    const by = (s: string) => pages.filter((p) => p.status === s).length;
    const total = pages.length;
    const hard = pages.filter((p) => p.route === "hard").length;
    const pre = by("queued") + by("docling");
    const s = (cond: boolean, running: boolean, action = false): StepState =>
      cond ? "done" : running ? (action ? "action" : "running") : "pending";
    const doclingDone = total - pre;
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
        state: s(at >= 3, at === 2, true),
        meta: `${by("approved")}/${total}`,
      },
      { key: "chunk", icon: <Layers />, state: s(at >= 5, at === 3 || at === 4, at === 3) },
      {
        key: "chunkReview",
        icon: <ListChecks />,
        state: s(at >= 6, at === 5, true),
        meta: doc.stats.chunks ? `${doc.stats.chunks_approved ?? 0}/${doc.stats.chunks}` : undefined,
      },
      { key: "index", icon: <FileText />, state: s(at >= 7, at === 6) },
    ] as { key: string; icon: React.ReactNode; state: StepState; meta?: string }[];
  }, [doc, pages]);
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
  const status = (s: (typeof steps)[number]) => `${label[s.state]}${s.meta ? ` · ${s.meta}` : ""}`;
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

function PageGrid({ docId, pages }: { docId: string; pages: Page[] }) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const colors: Record<string, string> = {
    neutral: "bg-muted text-muted-foreground border-border",
    info: "bg-info-soft text-info border-info/30",
    violet: "bg-violet-soft text-violet border-violet/30",
    warning: "bg-warning-soft text-foreground border-warning/50",
    success: "bg-success-soft text-success border-success/30",
    danger: "bg-danger-soft text-danger border-danger/40",
  };
  return (
    <div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(64px,1fr))] gap-2">
        {pages.map((p) => (
          <Tip
            key={p.page}
            content={
              <span>
                {t("review.page", { page: p.page })} · {t("review.bookPage", { page: p.book_page })}
                <br />
                {t(`pageStatus.${p.status}`)}
                {p.route ? ` · ${t(`route.${p.route}`)}` : ""}
                {p.route_reasons.length > 0 && (
                  <>
                    <br />
                    {p.route_reasons.map((r) => t(`reasons.${r}`)).join(", ")}
                  </>
                )}
              </span>
            }
          >
            <button
              onClick={() => nav(`/documents/${docId}/pages/${p.page}`)}
              className={cn(
                "relative flex h-16 flex-col items-center justify-center rounded-lg border text-xs font-medium transition hover:-translate-y-0.5 hover:shadow-md",
                colors[PAGE_TONE[p.status]],
              )}
            >
              <span className="text-[15px] font-semibold tabular-nums">{p.book_page}</span>
              <span className="text-[10px] opacity-80">p{p.page}</span>
              {p.route === "hard" && <span className="absolute right-1 top-1 size-1.5 rounded-full bg-violet" />}
              {p.status === "approved" && <Check className="absolute bottom-1 right-1 size-3" />}
              {["docling", "cu", "routed"].includes(p.status) && (
                <Loader2 className="absolute bottom-1 right-1 size-3 animate-spin" />
              )}
            </button>
          </Tip>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {(["queued", "docling", "cu", "review", "approved", "failed"] as const).map((s) => (
          <PageStatusBadge key={s} status={s} />
        ))}
        <span className="ml-2 flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-violet" /> {t("route.hard")}
        </span>
        <span className="ml-auto">{t("detail.gridLegend")}</span>
      </div>
    </div>
  );
}

function RoutingTable({ docId, pages, canEdit }: { docId: string; pages: Page[]; canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();
  const setOverride = async (p: Page, override: string) => {
    try {
      await api.post(`/documents/${docId}/pages/${p.page}/route`, { override });
      qc.invalidateQueries({ queryKey: ["pages", docId] });
    } catch (e) {
      toastError(e);
    }
  };
  const num = (v: number | null) => (v === null ? "—" : v.toFixed(2));
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("routing.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("routing.desc")}</p>
      </CardHeader>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr className="border-y border-border">
              <th className="px-4 py-2 font-medium">{t("common.page")}</th>
              <th className="px-3 py-2 font-medium">{t("routing.engine")}</th>
              <th className="px-3 py-2 font-medium">{t("routing.lowGrade")}</th>
              <th className="px-3 py-2 text-right font-medium">{t("routing.parse")}</th>
              <th className="px-3 py-2 text-right font-medium">{t("routing.layout")}</th>
              <th className="px-3 py-2 text-right font-medium">{t("routing.ocr")}</th>
              <th className="px-3 py-2 text-right font-medium">{t("routing.tables")}</th>
              <th className="px-3 py-2 text-right font-medium">{t("routing.figures")}</th>
              <th className="px-3 py-2 font-medium">{t("common.status")}</th>
              <th className="px-3 py-2 font-medium">{t("routing.reasons")}</th>
              <th className="px-4 py-2 font-medium">{t("routing.override")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {pages.map((p) => (
              <tr key={p.page} className="hover:bg-accent/40">
                <td className="px-4 py-2">
                  <Link to={`/documents/${docId}/pages/${p.page}`} className="font-medium hover:text-primary">
                    P{p.book_page}
                  </Link>
                  <span className="ml-1 text-xs text-muted-foreground">(p{p.page})</span>
                </td>
                <td className="px-3 py-2">
                  <Badge tone={p.engine === "docling" ? "primary" : "neutral"}>{p.engine || "—"}</Badge>
                </td>
                <td className="px-3 py-2">
                  <GradeBadge grade={p.scores.low_grade} />
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{num(p.scores.parse_score)}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{num(p.scores.layout_score)}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{num(p.scores.ocr_score)}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {p.features.n_tables}
                  {p.features.complex_tables > 0 && <span className="text-violet"> ({p.features.complex_tables})</span>}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{p.features.n_figures}</td>
                <td className="px-3 py-2">
                  <RouteBadge route={p.route} />
                </td>
                <td className="max-w-xs px-3 py-2 text-xs text-muted-foreground">
                  {p.route_reasons.map((r) => t(`reasons.${r}`)).join(" · ") || "—"}
                </td>
                <td className="px-4 py-2">
                  <Select
                    className="h-8 w-32 text-xs"
                    disabled={!canEdit}
                    value={p.route_override}
                    onValueChange={(v) => setOverride(p, v)}
                    options={[
                      { value: "auto", label: t("routing.auto") },
                      { value: "force_cu", label: t("routing.forceCu") },
                      { value: "skip_cu", label: t("routing.skipCu") },
                    ]}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function DocJobs({ docId }: { docId: string }) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const jobs = useQuery({
    queryKey: ["jobs", { doc_id: docId }],
    queryFn: () => api.get<Job[]>(`/jobs?doc_id=${docId}`),
    refetchInterval: 3000,
  });
  return (
    <Card>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr className="border-b border-border">
              <th className="px-4 py-2.5 font-medium">{t("jobs.step")}</th>
              <th className="px-3 py-2.5 font-medium">{t("common.page")}</th>
              <th className="px-3 py-2.5 font-medium">{t("common.status")}</th>
              <th className="px-3 py-2.5 font-medium">{t("jobs.attempts")}</th>
              <th className="px-3 py-2.5 font-medium">{t("jobs.duration")}</th>
              <th className="px-3 py-2.5 font-medium">{t("common.updated")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {jobs.data?.map((j) => (
              <tr
                key={j.id}
                className="cursor-pointer hover:bg-accent/40"
                onClick={() => nav(`/jobs?job=${encodeURIComponent(j.id)}`)}
              >
                <td className="px-4 py-2 font-medium">{t(`steps.${j.step}`)}</td>
                <td className="px-3 py-2 text-muted-foreground">{j.page ?? "—"}</td>
                <td className="px-3 py-2">
                  <JobStatusBadge status={j.status} />
                </td>
                <td className="px-3 py-2 tabular-nums">
                  {j.attempts}/{j.max_attempts}
                </td>
                <td className="px-3 py-2 tabular-nums text-muted-foreground">{fmtDuration(j.started_at, j.finished_at)}</td>
                <td className="px-3 py-2 text-muted-foreground">{fmtRelative(j.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export default function DocumentDetailPage() {
  const { docId = "" } = useParams();
  const { t } = useTranslation();
  const { can } = useAuth();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toastError = useToastError();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "overview";
  const [renaming, setRenaming] = useState(false);
  const doc = useQuery({ queryKey: ["document", docId], queryFn: () => api.get<Doc>(`/documents/${docId}`) });
  const pages = useQuery({ queryKey: ["pages", docId], queryFn: () => api.get<Page[]>(`/documents/${docId}/pages`) });
  const timer = useRef<number | undefined>(undefined);
  const onEvent = useCallback(
    (_e: JobEvent) => {
      if (timer.current !== undefined) return;
      timer.current = window.setTimeout(() => {
        timer.current = undefined;
        qc.invalidateQueries({ queryKey: ["document", docId] });
        qc.invalidateQueries({ queryKey: ["pages", docId] });
      }, 700);
    },
    [qc, docId],
  );
  const { events, connected } = useEventStream(`/api/stream/documents/${docId}`, onEvent);
  const steps = useSteps(doc.data, pages.data);
  // Chất lượng sau pipeline + số cảnh báo chưa xử lý (chỉ có khi đã qua bước nối trang)
  const quality = useQuery({
    queryKey: ["inspect", docId, "quality"],
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
      <div className="flex flex-col gap-4">
        <Skeleton className="h-10 w-80" />
        <Skeleton className="h-28" />
        <Skeleton className="h-80" />
      </div>
    );
  const d = doc.data;
  const total = d.page_to - d.page_from + 1;
  const nextReview = pages.data?.find((p) => p.status === "review");
  const failed = d.stats.failed ?? 0;
  const q = quality.data;
  const inspectUrl = `/documents/${docId}/view?tab=inspect`;

  return (
    <>
      <PageHeader
        breadcrumb={
          <span className="flex items-center gap-1">
            <Link to="/documents" className="hover:text-foreground">
              {t("nav.documents")}
            </Link>
            <ChevronRight className="size-3.5" />
            <span>{t(`kinds.${d.kind}`, { defaultValue: d.kind })}</span>
          </span>
        }
        title={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="break-words">{d.name}</span>
            {can("reviewer") && (
              <Button
                variant="ghost"
                size="iconSm"
                className="-ml-2 text-muted-foreground"
                onClick={() => setRenaming(true)}
                aria-label={t("common.rename")}
              >
                <Pencil />
              </Button>
            )}
            <DocStatusBadge status={d.status} />
          </span>
        }
        subtitle={`${t("documents.bookPages", { from: d.book_page_start, to: d.book_page_start + total - 1 })} · PDF p${d.page_from}–${d.page_to} / ${d.total_pdf_pages} · ${t("jobs.configVersion", { v: d.config_version })}`}
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => nav(inspectUrl)}>
              <ScanSearch />
              {t("detail.inspect")}
            </Button>
            <Button variant="outline" size="sm" onClick={() => window.open(`/api/documents/${docId}/source`, "_blank")}>
              <ExternalLink />
              {t("detail.openSource")}
            </Button>
            {can("reviewer") && failed > 0 && (
              <Button variant="outline" size="sm" onClick={() => action("retry_failed")}>
                <RefreshCw />
                {t("detail.retryFailed")}
              </Button>
            )}
            {can("reviewer") && ["ocr_review", "ready_for_chunking"].includes(d.status) && (
              <Button variant="outline" size="sm" onClick={() => action("restitch")}>
                <Layers />
                {t("detail.restitch")}
              </Button>
            )}
            {can("reviewer") && nextReview && (
              <Button size="sm" onClick={() => nav(`/documents/${docId}/pages/${nextReview.page}`)}>
                <UserCheck />
                {t("detail.reviewNext")}
              </Button>
            )}
            {can("reviewer") && d.status === "ready_for_chunking" && (
              <Button size="sm" onClick={() => action("start_chunking")}>
                <Layers />
                {t("detail.startChunking")}
              </Button>
            )}
            {["chunk_review", "indexed", "indexing"].includes(d.status) && (
              <Button size="sm" variant={d.status === "chunk_review" ? "default" : "outline"} onClick={() => nav(`/documents/${docId}/chunks`)}>
                <ListChecks />
                {t("detail.reviewChunks")}
              </Button>
            )}
          </>
        }
      />

      <Card className="mb-6">
        <CardContent className="flex flex-col gap-3 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-semibold">{t("detail.pipeline")}</p>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {(d.stats.hard ?? 0) > 0 && <Badge tone="violet">{t("detail.hardPages", { n: d.stats.hard })}</Badge>}
              {(d.stats.cu_skipped ?? 0) > 0 && (
                <Badge tone="warning">{t("detail.cuSkipped", { n: d.stats.cu_skipped })}</Badge>
              )}
              {failed > 0 && <Badge tone="danger">{t("pageStatus.failed")}: {failed}</Badge>}
              {q && (
                <Badge tone={q.grade === "good" ? "success" : q.grade === "fair" ? "warning" : "danger"}>
                  {t(`viewer.grade.${q.grade}`)} · {q.score}
                </Badge>
              )}
              {q && q.weak_open > 0 && (
                <Link to={inspectUrl}>
                  <Badge tone="warning">
                    <AlertTriangle />
                    {t("detail.weakOpen", { n: q.weak_open })}
                  </Badge>
                </Link>
              )}
            </div>
          </div>
          <Stepper steps={steps} />
          {d.status === "ocr_review" && (
            <p className="rounded-lg bg-warning-soft/60 px-3 py-2 text-sm">{t("detail.reviewHint")}</p>
          )}
          {d.status === "ready_for_chunking" && (
            <p className="rounded-lg bg-primary-soft px-3 py-2 text-sm text-primary">{t("detail.allApprovedHint")}</p>
          )}
        </CardContent>
      </Card>

      <RenameDialog doc={renaming ? d : null} onClose={() => setRenaming(false)} />
      <Tabs value={tab} onValueChange={(v) => setParams({ tab: v }, { replace: true })}>
        <TabsList className="mb-4">
          <TabsTrigger value="overview">
            <ScanText />
            {t("detail.pages")}
          </TabsTrigger>
          <TabsTrigger value="routing">
            <Route />
            {t("detail.routing")}
          </TabsTrigger>
          <TabsTrigger value="jobs">
            <ListChecks />
            {t("detail.jobs")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
            <Card className="xl:col-span-3">
              <CardHeader>
                <CardTitle>{t("detail.pages")}</CardTitle>
              </CardHeader>
              <CardContent>{pages.data && <PageGrid docId={docId} pages={pages.data} />}</CardContent>
            </Card>
            <LiveLog className="xl:col-span-2" events={events} connected={connected} height="h-[460px]" />
          </div>
        </TabsContent>
        <TabsContent value="routing">
          {pages.data && <RoutingTable docId={docId} pages={pages.data} canEdit={can("reviewer")} />}
        </TabsContent>
        <TabsContent value="jobs">
          <DocJobs docId={docId} />
        </TabsContent>
      </Tabs>
    </>
  );
}

/** /documents/:docId/review → trang đầu tiên đang chờ review (không còn thì về trang chi tiết). */
export function NextReviewRedirect() {
  const { docId = "" } = useParams();
  const pages = useQuery({ queryKey: ["pages", docId], queryFn: () => api.get<Page[]>(`/documents/${docId}/pages`) });
  if (pages.isError) return <Navigate to={`/documents/${docId}`} replace />;
  if (!pages.data) return <Skeleton className="h-80" />;
  const next = [...pages.data].sort((a, b) => a.page - b.page).find((p) => p.status === "review");
  return <Navigate to={next ? `/documents/${docId}/pages/${next.page}` : `/documents/${docId}`} replace />;
}
