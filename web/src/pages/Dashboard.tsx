import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2, FileText, Layers, ListChecks, Loader2, ScanText, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { PageHeader, StatCard } from "@/components/common";
import { DocStatusBadge } from "@/components/status";
import { docPageTotal, docProgress, useDocProgressLabel } from "@/components/docProgress";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, Progress, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Doc, DocStatus, Job } from "@/lib/types";
import { fmtRelative } from "@/lib/utils";

interface Dash {
  documents: number;
  documents_by_status: Record<DocStatus, number>;
  pages_to_review: number;
  chunks_to_review: number;
  jobs: Record<string, number>;
  queues: Record<string, number>;
  recent_failed: Job[];
  configured: Record<string, boolean>;
}

const STAGES: DocStatus[] = [
  "processing",
  "ocr_review",
  "ready_for_chunking",
  "chunking",
  "chunk_review",
  "indexing",
  "indexed",
  "failed",
];

export default function DashboardPage() {
  const { t } = useTranslation();
  const progressLabel = useDocProgressLabel();
  const nav = useNavigate();
  const { can } = useAuth();
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dash>("/dashboard"), refetchInterval: 5000 });
  const docs = useQuery({ queryKey: ["documents"], queryFn: () => api.get<Doc[]>("/documents"), refetchInterval: 5000 });
  const d = dash.data;
  const missing = d ? Object.entries(d.configured).filter(([, v]) => !v) : [];

  return (
    <>
      <PageHeader title={t("dashboard.title")} subtitle={t("dashboard.subtitle")} />
      {missing.length > 0 && can("admin") && (
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-warning/40 bg-warning-soft/60 px-4 py-3">
          <div className="flex items-center gap-2 text-sm">
            <AlertTriangle className="size-4 text-warning" />
            <span className="font-medium">{t("dashboard.setupHint")}</span>
            <span className="text-muted-foreground">
              {missing.map(([k]) => t(`settings.component.${k}`)).join(" · ")}
            </span>
          </div>
          <Button size="sm" variant="outline" onClick={() => nav("/settings?tab=services")}>
            {t("common.configure")}
            <ArrowRight />
          </Button>
        </div>
      )}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {d ? (
          <>
            <StatCard label={t("dashboard.documents")} value={d.documents} icon={<FileText />} onClick={() => nav("/documents")} />
            <StatCard
              label={t("dashboard.pagesToReview")}
              value={d.pages_to_review}
              icon={<ScanText />}
              tone="warning"
              onClick={() => nav("/documents")}
            />
            <StatCard label={t("dashboard.chunksToReview")} value={d.chunks_to_review} icon={<Layers />} tone="violet" />
            <StatCard
              label={t("dashboard.runningJobs")}
              value={(d.jobs.running ?? 0) + (d.jobs.queued ?? 0)}
              icon={<Loader2 className={d.jobs.running ? "animate-spin" : ""} />}
              tone="info"
              hint={d.jobs.failed ? `${d.jobs.failed} ${t("jobStatus.failed")}` : undefined}
              onClick={() => nav("/jobs")}
            />
          </>
        ) : (
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[88px] rounded-xl" />)
        )}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>{t("dashboard.recentDocs")}</CardTitle>
            <Button variant="ghost" size="sm" onClick={() => nav("/documents")}>
              {t("nav.documents")}
              <ArrowRight />
            </Button>
          </CardHeader>
          <CardContent className="pt-3">
            {docs.data && docs.data.length === 0 && (
              <EmptyState icon={<FileText />} title={t("documents.empty")} hint={t("documents.emptyHint")} />
            )}
            <ul className="divide-y divide-border">
              {docs.data?.slice(0, 6).map((doc) => {
                const total = docPageTotal(doc);
                const p = docProgress(doc);
                return (
                  <li key={doc.id}>
                    <Link to={`/documents/${doc.id}`} className="flex items-center gap-4 py-3 hover:opacity-80">
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium">{doc.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {t("documents.bookPages", { from: doc.book_page_start, to: doc.book_page_start + total - 1 })} ·{" "}
                          {fmtRelative(doc.updated_at)}
                        </p>
                      </div>
                      <div className="hidden w-40 sm:block">
                        <Progress value={p} tone={doc.status === "failed" ? "danger" : p === 100 ? "success" : "primary"} />
                        <p className="mt-1 text-right text-[11px] text-muted-foreground">{progressLabel(doc)}</p>
                      </div>
                      <DocStatusBadge status={doc.status} />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>{t("dashboard.byStatus")}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2.5 pt-3">
              {STAGES.map((s) => (
                <div key={s} className="flex items-center justify-between">
                  <DocStatusBadge status={s} />
                  <span className="font-mono text-sm tabular-nums">{d?.documents_by_status[s] ?? 0}</span>
                </div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>{t("dashboard.services")}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 pt-3">
              {d &&
                Object.entries(d.configured).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between text-sm">
                    <span>{t(`settings.component.${k}`)}</span>
                    {v ? (
                      <Badge tone="success">
                        <CheckCircle2 />
                        {t("common.configured")}
                      </Badge>
                    ) : (
                      <Badge tone="warning">{t("common.notConfigured")}</Badge>
                    )}
                  </div>
                ))}
              <div className="mt-2 border-t border-border pt-3">
                <p className="mb-2 text-xs font-medium text-muted-foreground">{t("dashboard.queues")}</p>
                <div className="flex flex-wrap gap-2">
                  {d &&
                    Object.entries(d.queues).map(([q, n]) => (
                      <Badge key={q} tone={n > 0 ? "info" : "neutral"}>
                        <ListChecks />
                        {q}: {t("dashboard.queueDepth", { n })}
                      </Badge>
                    ))}
                </div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>{t("dashboard.recentFailures")}</CardTitle>
            </CardHeader>
            <CardContent className="pt-3">
              {d && d.recent_failed.length === 0 && (
                <p className="text-sm text-muted-foreground">{t("dashboard.noFailures")}</p>
              )}
              <ul className="flex flex-col gap-2">
                {d?.recent_failed.map((j) => (
                  <li key={j.id}>
                    <Link to={`/jobs?job=${encodeURIComponent(j.id)}`} className="flex items-start gap-2 text-sm hover:opacity-80">
                      <XCircle className="mt-0.5 size-4 shrink-0 text-danger" />
                      <span className="min-w-0">
                        <span className="font-medium">{t(`steps.${j.step}`)}</span>
                        {j.page ? ` · p${j.page}` : ""}
                        <span className="block truncate text-xs text-muted-foreground">{j.error}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
