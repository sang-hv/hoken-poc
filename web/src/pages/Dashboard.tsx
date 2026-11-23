/** Dashboard: dải số liệu (bấm được), danh sách tài liệu cần xử lý, panel trạng thái hệ thống dạng <dl>. */
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/common";
import { DocState, DocTitle, NextStep, STATUS_DOT } from "@/components/docRow";
import { Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Doc, DocStatus, Job, ProvidersResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

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
const ACTION: DocStatus[] = ["failed", "ocr_review", "ready_for_chunking", "chunk_review"];

/** Một ô của dải số liệu: nhãn nhỏ, số lớn, ghi chú. Có `to` → cả ô là link. */
function Metric({ label, value, hint, to, tone }: { label: string; value: number; hint?: string; to?: string; tone?: "warning" }) {
  const body = (
    <>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("mt-1 text-2xl font-semibold tabular-nums", tone === "warning" && value > 0 && "text-warning")}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-danger">{hint}</p>}
    </>
  );
  const cls = "block bg-card px-5 py-4";
  return to ? (
    <Link to={to} className={cn(cls, "transition-colors hover:bg-accent")}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-border px-5 py-4 last:border-b-0">
      <h2 className="mb-2 text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-sm">
      <dt className="min-w-0 text-muted-foreground">{label}</dt>
      <dd className="shrink-0 tabular-nums">{children}</dd>
    </div>
  );
}

export default function DashboardPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dash>("/dashboard"), refetchInterval: 5000 });
  const docs = useQuery({ queryKey: ["documents"], queryFn: () => api.get<Doc[]>("/documents"), refetchInterval: 5000 });
  // Chỉ admin: lấy tên biến môi trường còn thiếu để hiện ngay trên dải cảnh báo
  const providers = useQuery({
    queryKey: ["providers"],
    queryFn: () => api.get<ProvidersResponse>("/settings/providers"),
    enabled: can("admin") && !!dash.data && Object.values(dash.data.configured).some((v) => !v),
  });
  // Chỉ admin: kết nối hạ tầng (DB / blob / queue) — chỉ hiện khi có lỗi
  const sys = useQuery({
    queryKey: ["system"],
    queryFn: () => api.get<{ health: Record<string, { ok: boolean }> }>("/system"),
    enabled: can("admin"),
    refetchInterval: 30000,
  });
  const down = Object.entries(sys.data?.health ?? {}).filter(([, h]) => !h.ok).map(([k]) => k);
  const d = dash.data;
  const missing = d ? Object.entries(d.configured).filter(([, v]) => !v) : [];
  const todo = (docs.data ?? [])
    .filter((x) => ACTION.includes(x.status) || (x.stats.failed ?? 0) > 0)
    .sort((a, b) => ACTION.indexOf(a.status) - ACTION.indexOf(b.status));

  return (
    <>
      <PageHeader title={t("dashboard.title")} subtitle={t("dashboard.subtitle")} />
      {down.length > 0 && (
        <div role="alert" className="mb-3 flex items-start gap-3 rounded-lg border border-danger/40 bg-danger-soft px-4 py-2.5 text-sm">
          <span className="mt-2 size-1.5 shrink-0 rounded-full bg-danger" aria-hidden />
          <p className="min-w-0">
            <span className="font-medium">{t("dashboard.infraDown")}</span>
            <span className="ml-2 font-mono text-xs uppercase text-muted-foreground">{down.join(" · ")}</span>
          </p>
        </div>
      )}
      {missing.length > 0 && can("admin") && (
        <div className="mb-6 flex items-start gap-3 rounded-lg border border-warning/40 bg-warning-soft px-4 py-2.5 text-sm">
          <span className="mt-2 size-1.5 shrink-0 rounded-full bg-warning" aria-hidden />
          <div className="min-w-0">
            <p className="font-medium">{t("dashboard.setupHint")}</p>
            <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-muted-foreground">
              {missing.map(([k]) => {
                const env = providers.data?.components[k]?.error?.env;
                return (
                  <li key={k}>
                    {t(`settings.component.${k}`)}
                    {env && <code className="ml-1.5 font-mono text-xs">{env}</code>}
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      )}

      {d ? (
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border lg:grid-cols-4">
          <Metric label={t("dashboard.documents")} value={d.documents} to="/documents" />
          <Metric label={t("dashboard.pagesToReview")} value={d.pages_to_review} tone="warning" to="/documents?status=action" />
          <Metric label={t("dashboard.chunksToReview")} value={d.chunks_to_review} tone="warning" to="/documents?status=action" />
          <Metric
            label={t("dashboard.runningJobs")}
            value={(d.jobs.running ?? 0) + (d.jobs.queued ?? 0)}
            hint={d.jobs.failed ? t("dashboard.failedCount", { n: d.jobs.failed }) : undefined}
          />
        </div>
      ) : (
        <Skeleton className="h-[92px] rounded-lg" />
      )}

      <div className="mt-6 grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <section className="overflow-hidden rounded-lg border border-border bg-card">
          <div className="flex h-11 items-center justify-between gap-3 border-b border-border px-4">
            <h2 className="text-sm font-semibold">
              {t("dashboard.needsAction")}
              {todo.length > 0 && <span className="ml-2 font-normal tabular-nums text-muted-foreground">{todo.length}</span>}
            </h2>
            <Link to="/documents" className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
              {t("dashboard.allDocs")}
              <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </div>
          {!docs.data ? (
            <div className="space-y-3 p-4">
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </div>
          ) : todo.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-muted-foreground">{t("dashboard.noAction")}</p>
          ) : (
            <ul className="divide-y divide-border">
              {todo.slice(0, 10).map((doc) => (
                <li
                  key={doc.id}
                  className="grid grid-cols-1 gap-2 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_13rem_auto] sm:items-center sm:gap-4"
                >
                  <DocTitle doc={doc} />
                  <DocState doc={doc} />
                  <div className="sm:justify-self-end">
                    <NextStep doc={doc} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <aside className="overflow-hidden rounded-lg border border-border bg-card">
          <Section title={t("dashboard.byStatus")}>
            <dl>
              {STAGES.map((s) => (
                <Row
                  key={s}
                  label={
                    <span className="flex items-center gap-2">
                      <span className={cn("size-2 shrink-0 rounded-full", STATUS_DOT[s].replace("animate-pulse-dot", ""))} aria-hidden />
                      {t(`docStatus.${s}`)}
                    </span>
                  }
                >
                  <span className={cn(!d?.documents_by_status[s] && "text-muted-foreground")}>{d?.documents_by_status[s] ?? 0}</span>
                </Row>
              ))}
            </dl>
          </Section>
          <Section title={t("dashboard.services")}>
            <dl>
              {d &&
                Object.entries(d.configured).map(([k, v]) => (
                  <Row key={k} label={t(`settings.component.${k}`)}>
                    <span className={v ? "text-muted-foreground" : "text-warning"}>
                      {v ? t("dashboard.configured") : t("dashboard.notConfigured")}
                    </span>
                  </Row>
                ))}
            </dl>
          </Section>
          <Section title={t("dashboard.queues")}>
            <dl>
              {d &&
                Object.entries(d.queues).map(([q, n]) => (
                  <Row key={q} label={<span className="font-mono text-xs">{q}</span>}>
                    <span className={cn(!n && "text-muted-foreground")}>{t("dashboard.queueDepth", { n })}</span>
                  </Row>
                ))}
            </dl>
          </Section>
          <Section title={t("dashboard.recentFailures")}>
            {d && d.recent_failed.length === 0 && <p className="text-sm text-muted-foreground">{t("dashboard.noFailures")}</p>}
            <ul className="flex flex-col gap-2.5">
              {d?.recent_failed.map((j) => (
                <li key={j.id}>
                  <Link to={`/documents/${j.doc_id}?tab=pipeline`} className="group flex items-start gap-2 text-sm">
                    <XCircle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
                    <span className="min-w-0">
                      <span className="font-medium group-hover:underline">{t(`steps.${j.step}`)}</span>
                      {j.page ? <span className="text-muted-foreground"> · p{j.page}</span> : ""}
                      <span className="block truncate text-xs text-muted-foreground" title={j.error}>
                        {j.error}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </Section>
        </aside>
      </div>
    </>
  );
}
