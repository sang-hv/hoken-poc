import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, ListChecks, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { PageHeader, useToastError } from "@/components/common";
import { LiveLog } from "@/components/LiveLog";
import { JobStatusBadge } from "@/components/status";
import { Badge, Button, Card, Dialog, EmptyState, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useEventStream } from "@/lib/sse";
import type { Job, JobEvent } from "@/lib/types";
import { fmtDateTime, fmtDuration, fmtRelative } from "@/lib/utils";

const STEPS = ["docling", "route", "cu", "stitch", "rerun", "chunk", "index"];
const STATUSES = ["queued", "running", "succeeded", "failed", "cancelled"];

function JobDialog({ jobId, onClose }: { jobId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const toastError = useToastError();
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get<Job & { events: JobEvent[] }>(`/jobs/${encodeURIComponent(jobId)}`),
    refetchInterval: 2000,
  });
  const { events, connected } = useEventStream(`/api/stream/jobs/${encodeURIComponent(jobId)}`);
  const j = job.data;
  const act = async (a: "retry" | "cancel") => {
    try {
      await api.post(`/jobs/${encodeURIComponent(jobId)}/${a}`);
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["job", jobId] });
    } catch (e) {
      toastError(e);
    }
  };
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      className="max-w-3xl"
      title={
        j ? (
          <span className="flex items-center gap-2">
            {t(`steps.${j.step}`)}
            {j.page ? ` · p${j.page}` : ""} <JobStatusBadge status={j.status} />
          </span>
        ) : (
          t("common.loading")
        )
      }
      description={j?.id}
      footer={
        j &&
        can("reviewer") && (
          <>
            {["queued", "running"].includes(j.status) && (
              <Button variant="outline" onClick={() => act("cancel")}>
                <Ban />
                {t("common.cancelJob")}
              </Button>
            )}
            {["failed", "cancelled", "succeeded"].includes(j.status) && (
              <Button onClick={() => act("retry")}>
                <RefreshCw />
                {t("common.retry")}
              </Button>
            )}
          </>
        )
      }
    >
      {!j ? (
        <Skeleton className="h-60" />
      ) : (
        <div className="flex flex-col gap-4">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs text-muted-foreground">{t("jobs.document")}</dt>
              <dd>
                <Link to={`/documents/${j.doc_id}`} className="hover:text-primary" onClick={onClose}>
                  {j.doc_name || j.doc_id}
                </Link>
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("jobs.queue")}</dt>
              <dd>
                <Badge>{j.queue}</Badge>
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("jobs.attempts")}</dt>
              <dd className="tabular-nums">
                {j.attempts}/{j.max_attempts}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("common.created")}</dt>
              <dd>{fmtDateTime(j.created_at)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("jobs.duration")}</dt>
              <dd>{fmtDuration(j.started_at, j.finished_at)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("common.version")}</dt>
              <dd>{t("jobs.configVersion", { v: j.config_version })}</dd>
            </div>
          </dl>
          {j.error && <pre className="whitespace-pre-wrap rounded-lg bg-danger-soft p-3 text-xs text-danger">{j.error}</pre>}
          {Object.keys(j.params).length > 0 && (
            <div>
              <p className="mb-1 text-xs text-muted-foreground">{t("jobs.params")}</p>
              <pre className="whitespace-pre-wrap rounded-lg bg-muted p-3 text-xs">{JSON.stringify(j.params, null, 2)}</pre>
            </div>
          )}
          <LiveLog events={events.length ? events : j.events} connected={connected} showStep={false} height="h-72" />
        </div>
      )}
    </Dialog>
  );
}

export default function JobsPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState("all");
  const [step, setStep] = useState("all");
  const q = new URLSearchParams();
  if (status !== "all") q.set("status", status);
  if (step !== "all") q.set("step", step);
  const jobs = useQuery({ queryKey: ["jobs", status, step], queryFn: () => api.get<Job[]>(`/jobs?${q}`), refetchInterval: 3000 });
  const open = params.get("job");

  return (
    <>
      <PageHeader title={t("jobs.title")} subtitle={t("jobs.subtitle")} />
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
          <Select
            className="w-44"
            value={status}
            onValueChange={setStatus}
            options={[{ value: "all", label: t("common.all") }, ...STATUSES.map((s) => ({ value: s, label: t(`jobStatus.${s}`) }))]}
          />
          <Select
            className="w-56"
            value={step}
            onValueChange={setStep}
            options={[{ value: "all", label: t("common.all") }, ...STEPS.map((s) => ({ value: s, label: t(`steps.${s}`) }))]}
          />
        </div>
        {jobs.isLoading && <Skeleton className="m-4 h-40" />}
        {jobs.data && jobs.data.length === 0 && <EmptyState icon={<ListChecks />} title={t("jobs.empty")} />}
        {jobs.data && jobs.data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="px-4 py-2.5 font-medium">{t("jobs.step")}</th>
                  <th className="px-3 py-2.5 font-medium">{t("jobs.document")}</th>
                  <th className="px-3 py-2.5 font-medium">{t("common.page")}</th>
                  <th className="px-3 py-2.5 font-medium">{t("common.status")}</th>
                  <th className="px-3 py-2.5 font-medium">{t("jobs.attempts")}</th>
                  <th className="px-3 py-2.5 font-medium">{t("jobs.duration")}</th>
                  <th className="px-3 py-2.5 font-medium">{t("jobs.error")}</th>
                  <th className="px-3 py-2.5 font-medium">{t("common.updated")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {jobs.data.map((j) => (
                  <tr key={j.id} className="cursor-pointer hover:bg-accent/40" onClick={() => setParams({ job: j.id })}>
                    <td className="px-4 py-2.5 font-medium">{t(`steps.${j.step}`)}</td>
                    <td className="max-w-56 truncate px-3 py-2.5">{j.doc_name}</td>
                    <td className="px-3 py-2.5 text-muted-foreground">{j.page ?? "—"}</td>
                    <td className="px-3 py-2.5">
                      <JobStatusBadge status={j.status} />
                    </td>
                    <td className="px-3 py-2.5 tabular-nums">
                      {j.attempts}/{j.max_attempts}
                    </td>
                    <td className="px-3 py-2.5 tabular-nums text-muted-foreground">{fmtDuration(j.started_at, j.finished_at)}</td>
                    <td className="max-w-64 truncate px-3 py-2.5 text-xs text-danger">{j.error}</td>
                    <td className="px-3 py-2.5 text-muted-foreground">{fmtRelative(j.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {open && <JobDialog jobId={open} onClose={() => setParams({})} />}
    </>
  );
}
