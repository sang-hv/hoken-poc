import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Check, CheckCheck, Database, Merge, Save, Scissors, Undo2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Markdown, useToastError } from "@/components/common";
import { ConfidenceBadge, DocStatusBadge } from "@/components/status";
import { Badge, Button, Checkbox, EmptyState, Field, Input, Progress, Select, Skeleton, Switch, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Chunk, Doc, JobEvent } from "@/lib/types";
import { cn, pct } from "@/lib/utils";

export default function ChunkReviewPage() {
  const { docId = "" } = useParams();
  const { t } = useTranslation();
  const { can } = useAuth();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toastError = useToastError();
  const canEdit = can("reviewer");
  const doc = useQuery({ queryKey: ["document", docId], queryFn: () => api.get<Doc>(`/documents/${docId}`), refetchInterval: 4000 });
  const chunks = useQuery({ queryKey: ["chunks", docId], queryFn: () => api.get<Chunk[]>(`/documents/${docId}/chunks`) });
  const events = useQuery({
    queryKey: ["events", docId],
    queryFn: () => api.get<JobEvent[]>(`/documents/${docId}/events?limit=1000`),
  });

  const [sort, setSort] = useState<"seq" | "confidence">("confidence");
  const [onlyIssues, setOnlyIssues] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [form, setForm] = useState({ text: "", item_code: "", title: "", page_from: 0, page_to: 0 });
  const [busy, setBusy] = useState<string | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);

  const all = chunks.data ?? [];
  const list = useMemo(() => {
    let l = all.slice();
    if (onlyIssues) l = l.filter((c) => c.violations.length > 0 || c.confidence < 0.7);
    if (sort === "confidence") l.sort((a, b) => Number(a.status !== "draft") - Number(b.status !== "draft") || a.confidence - b.confidence);
    return l;
  }, [all, sort, onlyIssues]);
  const active = all.find((c) => c.id === activeId) ?? null;
  const approved = all.filter((c) => c.status !== "draft").length;

  useEffect(() => {
    if (!activeId && list.length) setActiveId(list[0].id);
  }, [list, activeId]);
  useEffect(() => {
    if (active)
      setForm({
        text: active.text,
        item_code: active.item_code,
        title: active.title,
        page_from: active.page_from,
        page_to: active.page_to,
      });
  }, [active?.id, active?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty =
    !!active &&
    (form.text !== active.text || form.item_code !== active.item_code || form.title !== active.title ||
      form.page_from !== active.page_from || form.page_to !== active.page_to);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["chunks", docId] });
    qc.invalidateQueries({ queryKey: ["document", docId] });
    qc.invalidateQueries({ queryKey: ["events", docId] });
  };
  const run = async (key: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(key);
    try {
      await fn();
      if (ok) toast.success(ok);
      refresh();
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(null);
    }
  };

  const rounds = useMemo(
    () => (events.data ?? []).filter((e) => e.code === "chunk.round" && active && e.params.item_code === active.item_code),
    [events.data, active],
  );
  const chunkReview = doc.data && ["chunk_review", "indexed"].includes(doc.data.status);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 overflow-x-auto border-b border-border bg-card px-4 py-2 [&>*]:shrink-0">
        <Button variant="ghost" size="sm" onClick={() => nav(`/documents/${docId}`)}>
          <ArrowLeft />
          <span className="hidden max-w-40 truncate 2xl:inline">{doc.data?.name}</span>
        </Button>
        <span className="text-sm font-semibold">{t("chunks.title")}</span>
        {doc.data && <DocStatusBadge status={doc.data.status} />}
        <div className="flex w-48 items-center gap-2">
          <Progress value={pct(approved, all.length)} tone={approved === all.length ? "success" : "primary"} />
          <span className="whitespace-nowrap text-xs text-muted-foreground">
            {t("chunks.approvedCount", { n: approved, total: all.length })}
          </span>
        </div>
        <div className="flex-1" />
        {canEdit && chunkReview && (
          <>
            <Button
              variant="outline"
              size="sm"
              disabled={selected.size < 2}
              loading={busy === "merge"}
              aria-label={t("chunks.merge")}
              title={t("chunks.merge")}
              onClick={() =>
                run("merge", async () => {
                  const merged = await api.post<Chunk>(`/documents/${docId}/chunks/merge`, { ids: [...selected] });
                  setSelected(new Set());
                  setActiveId(merged.id);
                })
              }
            >
              <Merge />
              <span className="hidden xl:inline">{t("chunks.merge")}</span>
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={selected.size === 0}
              loading={busy === "approveSel"}
              aria-label={t("chunks.approveSelected", { n: selected.size })}
              title={t("chunks.approveSelected", { n: selected.size })}
              onClick={() =>
                run("approveSel", async () => {
                  await api.post(`/documents/${docId}/chunks/approve`, { ids: [...selected], approved: true });
                  setSelected(new Set());
                })
              }
            >
              <Check />
              <span className="hidden xl:inline">{t("chunks.approveSelected", { n: selected.size })}</span>
            </Button>
            <Button
              variant="outline"
              size="sm"
              loading={busy === "approveAll"}
              aria-label={t("chunks.approveAll")}
              title={t("chunks.approveAll")}
              onClick={() =>
                run("approveAll", () =>
                  api.post(`/documents/${docId}/chunks/approve`, { ids: all.map((c) => c.id), approved: true }),
                )
              }
            >
              <CheckCheck />
              <span className="hidden xl:inline">{t("chunks.approveAll")}</span>
            </Button>
            <Button
              size="sm"
              disabled={approved !== all.length || all.length === 0}
              loading={busy === "index"}
              onClick={() => run("index", () => api.post(`/documents/${docId}/actions/index`), t("common.saved"))}
            >
              <Database />
              {t("detail.startIndex")}
            </Button>
          </>
        )}
      </div>

      {chunks.isLoading ? (
        <Skeleton className="m-4 h-full" />
      ) : all.length === 0 ? (
        <EmptyState title={t("chunks.empty")} />
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[400px_1fr]">
          <aside className="flex min-h-0 flex-col border-r border-border">
            <div className="flex flex-wrap items-center gap-3 border-b border-border px-3 py-2 text-xs">
              <Select
                className="h-8 w-48 text-xs"
                value={sort}
                onValueChange={(v) => setSort(v as "seq" | "confidence")}
                options={[
                  { value: "confidence", label: t("chunks.sortConfidence") },
                  { value: "seq", label: t("chunks.sortSeq") },
                ]}
              />
              <label className="flex items-center gap-2 text-muted-foreground">
                <Switch checked={onlyIssues} onCheckedChange={setOnlyIssues} />
                {t("chunks.onlyIssues")}
              </label>
            </div>
            <ul className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
              {list.map((c) => (
                <li
                  key={c.id}
                  onClick={() => setActiveId(c.id)}
                  className={cn(
                    "flex cursor-pointer gap-3 px-3 py-2.5 transition hover:bg-accent/60",
                    c.id === activeId && "bg-primary-soft/70",
                  )}
                >
                  <div onClick={(e) => e.stopPropagation()} className="pt-0.5">
                    <Checkbox
                      checked={selected.has(c.id)}
                      onCheckedChange={(v) => {
                        const s = new Set(selected);
                        if (v) s.add(c.id);
                        else s.delete(c.id);
                        setSelected(s);
                      }}
                    />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-[11px] text-muted-foreground">#{c.seq}</span>
                      <Badge tone="primary" className="font-mono">
                        {c.item_code || "—"}
                      </Badge>
                      <ConfidenceBadge value={c.confidence} />
                      {c.violations.length > 0 && (
                        <Badge tone="warning">
                          <AlertTriangle />
                          {c.violations.length}
                        </Badge>
                      )}
                      <span className="ml-auto">
                        {c.status !== "draft" ? (
                          <Badge tone="success">
                            <Check />
                          </Badge>
                        ) : null}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{c.text}</p>
                    <p className="mt-0.5 text-[11px] text-muted-foreground">
                      P{c.page_from}
                      {c.page_to !== c.page_from ? `–${c.page_to}` : ""} · {c.text.length}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </aside>

          <section className="min-h-0 overflow-y-auto">
            {active && (
              <div className="mx-auto flex max-w-4xl flex-col gap-5 p-6">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-semibold">
                    #{active.seq} · {active.item_code || "—"}
                  </h2>
                  <ConfidenceBadge value={active.confidence} />
                  <Badge>
                    {t("chunks.rules")} {Math.round(active.rule_score * 100)}%
                  </Badge>
                  {active.llm_score !== null && (
                    <Badge tone="violet">
                      {t("chunks.llm")} {Math.round(active.llm_score * 100)}%
                    </Badge>
                  )}
                  {active.rounds > 0 && <Badge tone="info">{t("chunks.rounds")}: {active.rounds}</Badge>}
                  <div className="flex-1" />
                  {canEdit && chunkReview && (
                    <>
                      <Button
                        variant="outline"
                        size="sm"
                        loading={busy === "split"}
                        onClick={() => {
                          const pos = textRef.current?.selectionStart ?? 0;
                          run("split", () => api.post(`/documents/${docId}/chunks/${active.id}/split`, { offset: pos }));
                        }}
                      >
                        <Scissors />
                        {t("chunks.split")}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!dirty}
                        loading={busy === "save"}
                        onClick={() =>
                          run("save", () => api.put(`/documents/${docId}/chunks/${active.id}`, form), t("common.saved"))
                        }
                      >
                        <Save />
                        {t("chunks.saveChunk")}
                      </Button>
                      {active.status === "draft" ? (
                        <Button
                          size="sm"
                          loading={busy === "approve"}
                          onClick={() =>
                            run("approve", async () => {
                              if (dirty) await api.put(`/documents/${docId}/chunks/${active.id}`, form);
                              await api.post(`/documents/${docId}/chunks/approve`, { ids: [active.id], approved: true });
                              const nextDraft = list.find((c) => c.status === "draft" && c.id !== active.id);
                              if (nextDraft) setActiveId(nextDraft.id);
                            })
                          }
                        >
                          <Check />
                          {t("chunks.approve")}
                        </Button>
                      ) : (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() =>
                            run("unapprove", () =>
                              api.post(`/documents/${docId}/chunks/approve`, { ids: [active.id], approved: false }),
                            )
                          }
                        >
                          <Undo2 />
                          {t("chunks.unapprove")}
                        </Button>
                      )}
                    </>
                  )}
                </div>

                {active.violations.length > 0 && (
                  <div className="rounded-xl border border-warning/40 bg-warning-soft/60 px-4 py-3">
                    <p className="mb-1 flex items-center gap-2 text-sm font-medium">
                      <AlertTriangle className="size-4 text-warning" />
                      {t("chunks.violations")}
                    </p>
                    <ul className="ml-6 list-disc text-sm">
                      {active.violations.map((v) => (
                        <li key={v}>{t(`violations.${v}`, { defaultValue: v })}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <Field label={t("chunks.itemCode")}>
                    <Input
                      className="font-mono"
                      disabled={!canEdit}
                      value={form.item_code}
                      onChange={(e) => setForm({ ...form, item_code: e.target.value })}
                    />
                  </Field>
                  <Field label={t("chunks.titleField")} className="col-span-2 sm:col-span-1">
                    <Input disabled={!canEdit} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
                  </Field>
                  <Field label={`${t("chunks.pages")} (from)`}>
                    <Input
                      type="number"
                      disabled={!canEdit}
                      value={form.page_from}
                      onChange={(e) => setForm({ ...form, page_from: Number(e.target.value) })}
                    />
                  </Field>
                  <Field label="(to)">
                    <Input
                      type="number"
                      disabled={!canEdit}
                      value={form.page_to}
                      onChange={(e) => setForm({ ...form, page_to: Number(e.target.value) })}
                    />
                  </Field>
                </div>
                <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                  <Field label={t("chunks.text")}>
                    <Textarea
                      ref={textRef}
                      rows={18}
                      disabled={!canEdit}
                      className="font-mono text-[13px] leading-relaxed"
                      value={form.text}
                      onChange={(e) => setForm({ ...form, text: e.target.value })}
                    />
                  </Field>
                  <Field label={t("review.preview")}>
                    <div className="h-full max-h-[440px] overflow-auto rounded-lg border border-border bg-card p-4">
                      <Markdown text={form.text} />
                    </div>
                  </Field>
                </div>
                {rounds.length > 0 && (
                  <div>
                    <p className="mb-2 text-sm font-medium">{t("chunks.roundsLog")}</p>
                    <ol className="flex flex-wrap gap-2">
                      {rounds.map((e) => (
                        <li key={e.id}>
                          <Badge tone={Number(e.params.violations) === 0 ? "success" : "warning"}>
                            #{String(e.params.round)} · {String(e.params.chunks)} chunks · {String(e.params.violations)}
                          </Badge>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
