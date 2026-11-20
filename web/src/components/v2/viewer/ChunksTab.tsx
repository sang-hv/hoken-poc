/** Tab チャンク (cấp tài liệu): danh sách chunk (phân trang ở server + danh sách ảo — chịu được hàng nghìn chunk),
 *  dải trang (chunk có thể trải nhiều trang), điểm, vi phạm luật, ⚠ khi trang của chunk còn điểm yếu. Sửa / tách /
 *  gộp với chunk sau; tài liệu tự chạy → lưu xong tự duyệt + index lại (backend).
 *  Route: /documents/:docId?tab=chunks&chunk=<id> */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  Columns2,
  FileText,
  Layers,
  Loader2,
  Merge,
  Pencil,
  Save,
  Scissors,
  Search,
  Undo2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Markdown, useToastError } from "@/components/common";
import { ConfidenceBadge } from "@/components/status";
import { Badge, Button, EmptyState, Field, Input, Skeleton, Textarea, Tip } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useDebounced } from "@/lib/hooks";
import type { Chunk, Doc } from "@/lib/types";
import type { ChunkSummary } from "@/lib/v2types";
import { cn } from "@/lib/utils";
import { ChunkCompareDialog } from "./ChunkCompareDialog";
import { type ChunkFilter, ChunkList, type ChunkListParams, ck, useChunkHead, useChunkIndex } from "./ChunkList";
import { reviewStage } from "./ReviewGate";
import { QueryError, type ViewerTab, bookToPdf, useDocMeta, useQuality, vk } from "./shared";

const EDITABLE = ["chunk_review", "indexed"];

function pdfRange(doc: Doc | undefined, c: Pick<Chunk, "page_from" | "page_to">): [number, number] {
  return doc ? [bookToPdf(doc, c.page_from), bookToPdf(doc, c.page_to)] : [c.page_from, c.page_to];
}

export function ChunksTab({
  docId,
  canEdit,
  selectedId,
  onSelect,
  onGo,
}: {
  docId: string;
  canEdit: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onGo: (tab: ViewerTab, page: number) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();
  const doc = useDocMeta(docId);
  const quality = useQuality(docId);
  const d = doc.data;
  const reviewing = reviewStage(d) === "chunk";

  // Bộ lọc: đang dừng ở チャンクレビュー → mặc định chỉ hiện chunk cần xem
  const [filter, setFilter] = useState<ChunkFilter | null>(null);
  useEffect(() => {
    if (d && filter === null) setFilter(reviewing ? "issues" : "all");
  }, [d, filter, reviewing]);
  const [query, setQuery] = useState("");
  const [pageText, setPageText] = useState("");
  const q = useDebounced(query.trim(), 300);
  const pageNum = useDebounced(Number(pageText) > 0 ? Math.floor(Number(pageText)) : null, 300);
  const params: ChunkListParams = { filter: filter ?? "all", q, page: pageNum };

  const head = useChunkHead(docId, params, filter !== null);
  const total = head.data?.total ?? 0;
  const counts = head.data?.counts ?? { all: d?.stats.chunks ?? 0, issues: d?.stats.chunks_flagged ?? 0 };
  const focusIndex = useChunkIndex(docId, params, selectedId);
  const chunk = useQuery({
    queryKey: ck.one(docId, selectedId ?? ""),
    queryFn: () => api.get<Chunk & { next_id: string | null }>(`/documents/${docId}/chunks/${selectedId}`),
    enabled: !!selectedId,
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2,
  });
  const active = chunk.data ?? null;

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ text: "", item_code: "", title: "" });
  const [busy, setBusy] = useState<string | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  /** Popup 原本と比較 đang mở ở trang PDF này (null = đóng) */
  const [compare, setCompare] = useState<number | null>(null);

  /** Trang PDF còn điểm yếu chưa xử lý */
  const weakPages = useMemo(
    () => new Set((quality.data?.pages ?? []).filter((p) => p.weak_open > 0).map((p) => p.page)),
    [quality.data],
  );
  const weakIn = (c: Pick<Chunk, "page_from" | "page_to">) => {
    const [a, b] = pdfRange(d, c);
    const out: number[] = [];
    for (let p = a; p <= b; p++) if (weakPages.has(p)) out.push(p);
    return out;
  };
  const editable = canEdit && !!d && EDITABLE.includes(d.status);
  const next = active?.next_id ? { id: active.next_id, seq: active.seq + 1 } : undefined;

  // Chưa chọn, hoặc chunk đã bị gộp / xoá → chọn dòng đầu danh sách
  const first = head.data?.items[0]?.id;
  const missing = chunk.error instanceof ApiError && chunk.error.status === 404;
  useEffect(() => {
    if (first && (!selectedId || missing)) onSelect(first);
  }, [first, selectedId, missing, onSelect]);
  useEffect(() => {
    setEditing(false);
    if (active) setForm({ text: active.text, item_code: active.item_code, title: active.title });
  }, [active?.id, active?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty =
    !!active && (form.text !== active.text || form.item_code !== active.item_code || form.title !== active.title);

  const run = async (key: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(key);
    try {
      await fn();
      if (ok) toast.success(ok);
      setEditing(false);
      qc.invalidateQueries({ queryKey: ck.list(docId) });
      qc.invalidateQueries({ queryKey: ["chunk", docId] });
      qc.invalidateQueries({ queryKey: vk.all(docId) });
      qc.invalidateQueries({ queryKey: ["document", docId] });
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(null);
    }
  };
  // Tự index lại sau khi sửa: tài liệu tự chạy và không đang dừng ở チャンクレビュー (cùng điều kiện với backend)
  const autoIndex = !!d?.auto_review && d?.review_hold !== "chunk";
  const saved = autoIndex ? t("viewer.chunkTab.savedReindex") : t("common.saved");

  if (head.isError) return <QueryError error={head.error} onRetry={() => head.refetch()} className="m-auto" />;
  if (!d || filter === null || (head.isLoading && !head.data))
    return (
      <div className="grid flex-1 grid-cols-1 gap-4 p-4 lg:grid-cols-[380px_1fr]">
        <Skeleton className="h-full min-h-60" />
        <Skeleton className="h-full min-h-60" />
      </div>
    );
  if (counts.all === 0)
    return (
      <div className="flex flex-1 items-center justify-center">
        <EmptyState icon={<Layers />} title={t("viewer.chunkTab.empty")} hint={t("viewer.chunkTab.emptyHint")} />
      </div>
    );

  const [pa, pb] = active ? pdfRange(d, active) : [0, 0];
  const activeWeak = active ? weakIn(active) : [];

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[380px_minmax(0,1fr)]">
      {/* ------------------------------------------------ danh sách */}
      <aside className="flex max-h-[45vh] min-h-0 flex-col border-b border-border bg-card lg:max-h-none lg:border-b-0 lg:border-r">
        <div className="flex flex-col gap-2 border-b border-border p-3">
          <div className="flex gap-2">
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("viewer.chunkTab.search")}
                aria-label={t("viewer.chunkTab.search")}
                className="h-8 pl-8 text-sm"
              />
            </div>
            <Input
              type="number"
              min={1}
              value={pageText}
              onChange={(e) => setPageText(e.target.value)}
              placeholder={t("viewer.chunkTab.pagePlaceholder")}
              aria-label={t("viewer.chunkTab.pageFilter")}
              title={t("viewer.chunkTab.pageFilter")}
              className="h-8 w-20 text-sm"
            />
          </div>
          <div role="tablist" className="flex rounded-lg bg-muted p-0.5 text-xs font-medium">
            {(["all", "issues"] as ChunkFilter[]).map((k) => (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={filter === k}
                onClick={() => setFilter(k)}
                className={cn(
                  "flex-1 cursor-pointer rounded-md px-2 py-1 transition",
                  filter === k ? "bg-card text-foreground shadow-card" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {k === "all" ? t("viewer.chunkTab.all", { n: counts.all }) : t("viewer.chunkTab.issues", { n: counts.issues })}
              </button>
            ))}
          </div>
          {(q || pageNum) && (
            <p className="text-[11px] text-muted-foreground">{t("viewer.chunkTab.matches", { n: total })}</p>
          )}
        </div>
        {total === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">{t("viewer.chunkTab.noMatch")}</p>
        ) : (
          <ChunkList
            docId={docId}
            params={params}
            total={total}
            selectedId={selectedId}
            onSelect={onSelect}
            scrollToIndex={focusIndex.data ?? null}
            pdfRange={(c: ChunkSummary) => pdfRange(d, c)}
            weak={(c: ChunkSummary) => weakIn(c).length > 0}
          />
        )}
      </aside>

      {active && (
        <ChunkCompareDialog
          docId={docId}
          chunk={active}
          open={compare !== null}
          onOpenChange={(o) => !o && setCompare(null)}
          startPage={compare}
          onInspect={(p) => {
            setCompare(null);
            onGo("inspect", p);
          }}
        />
      )}
      {/* ------------------------------------------------ chi tiết */}
      <section className="min-h-0 overflow-y-auto">
        {active && (
          <div className="mx-auto flex max-w-4xl flex-col gap-4 p-4 lg:p-6">
            <div className="flex flex-wrap items-start gap-2">
              <div className="min-w-0 flex-1">
                <h2 className="flex flex-wrap items-center gap-2 text-lg font-semibold">
                  <span className="font-mono text-sm text-muted-foreground">#{active.seq}</span>
                  <span className="font-mono">{active.item_code || "—"}</span>
                  {active.title && <span className="min-w-0 break-words text-base">{active.title}</span>}
                </h2>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
                  <ConfidenceBadge value={active.confidence} />
                  <Badge>
                    {t("chunks.rules")} {Math.round(active.rule_score * 100)}%
                  </Badge>
                  {active.llm_score !== null && (
                    <Badge tone="violet">
                      {t("chunks.llm")} {Math.round(active.llm_score * 100)}%
                    </Badge>
                  )}
                  <Badge tone={active.status === "draft" ? "warning" : "success"}>
                    {t(`viewer.chunkTab.status.${active.status}`)}
                  </Badge>
                  {active.edited_by && active.edited_by !== "auto" && (
                    <span className="text-muted-foreground">{t("viewer.chunkTab.editedBy", { by: active.edited_by })}</span>
                  )}
                </div>
              </div>
              {editable && !editing && (
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                    <Pencil />
                    {t("viewer.chunkTab.edit")}
                  </Button>
                  {next && (
                    <Tip content={t("viewer.chunkTab.mergeTip", { seq: next.seq })}>
                      <Button
                        variant="outline"
                        size="sm"
                        loading={busy === "merge"}
                        onClick={() =>
                          run(
                            "merge",
                            () => api.post(`/documents/${docId}/chunks/merge`, { ids: [active.id, next.id] }),
                            saved,
                          )
                        }
                      >
                        <Merge />
                        {t("viewer.chunkTab.mergeNext")}
                      </Button>
                    </Tip>
                  )}
                  {reviewing &&
                    (active.status === "draft" ? (
                      <Button
                        size="sm"
                        loading={busy === "approve"}
                        onClick={() =>
                          run("approve", () =>
                            api.post(`/documents/${docId}/chunks/approve`, { ids: [active.id], approved: true }),
                          )
                        }
                      >
                        <Check />
                        {t("chunks.approve")}
                      </Button>
                    ) : (
                      <Button
                        variant="secondary"
                        size="sm"
                        loading={busy === "unapprove"}
                        onClick={() =>
                          run("unapprove", () =>
                            api.post(`/documents/${docId}/chunks/approve`, { ids: [active.id], approved: false }),
                          )
                        }
                      >
                        <Undo2 />
                        {t("chunks.unapprove")}
                      </Button>
                    ))}
                </div>
              )}
            </div>

            {/* trang của chunk: một chunk có thể trải nhiều trang */}
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm">
              <span className="font-medium">{t("viewer.chunks.pages", { from: pa, to: pb })}</span>
              <span className="text-xs text-muted-foreground">
                {t("viewer.chunkTab.bookPages", { from: active.page_from, to: active.page_to })}
              </span>
              {pb > pa && <Badge tone="violet">{t("viewer.chunkTab.span", { n: pb - pa + 1 })}</Badge>}
              <span className="flex-1" />
              {Array.from({ length: pb - pa + 1 }, (_, i) => pa + i).map((p) => (
                <Tip key={p} content={t("viewer.chunkTab.comparePage", { page: p })}>
                  <Button
                    variant="ghost"
                    size="sm"
                    className={cn("h-7 px-2", weakPages.has(p) && "text-warning")}
                    onClick={() => setCompare(p)}
                  >
                    {weakPages.has(p) ? <AlertTriangle /> : <FileText />}
                    p.{p}
                  </Button>
                </Tip>
              ))}
              <Button variant="soft" size="sm" className="h-7" onClick={() => setCompare(pa)}>
                <Columns2 />
                {t("viewer.compare.title")}
              </Button>
            </div>

            {activeWeak.length > 0 && (
              <p className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning-soft px-3 py-2 text-sm">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
                {t("viewer.chunkTab.weakHint", { pages: activeWeak.map((p) => `p.${p}`).join(", ") })}
              </p>
            )}
            {active.violations.length > 0 && (
              <div className="rounded-lg border border-warning/40 bg-warning-soft/60 px-3 py-2 text-sm">
                <p className="mb-1 font-medium">{t("chunks.violations")}</p>
                <ul className="ml-5 list-disc">
                  {active.violations.map((v) => (
                    <li key={v}>{t(`violations.${v}`, { defaultValue: v })}</li>
                  ))}
                </ul>
              </div>
            )}
            {canEdit && !editable && (
              <p className="flex items-center gap-2 rounded-lg bg-info-soft px-3 py-2 text-sm text-info">
                <Loader2 className="size-4 animate-spin" />
                {t("viewer.chunkTab.busy")}
              </p>
            )}

            {editing ? (
              <div className="flex flex-col gap-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-[12rem_1fr]">
                  <Field label={t("chunks.itemCode")}>
                    <Input
                      className="font-mono"
                      value={form.item_code}
                      onChange={(e) => setForm({ ...form, item_code: e.target.value })}
                    />
                  </Field>
                  <Field label={t("chunks.titleField")}>
                    <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
                  </Field>
                </div>
                <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                  <Field label={t("chunks.text")} hint={t("viewer.chunkTab.splitHint")}>
                    <Textarea
                      ref={textRef}
                      rows={18}
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
                <div className="flex flex-wrap items-center gap-2">
                  {autoIndex && <p className="text-xs text-muted-foreground">{t("viewer.chunkTab.autoNote")}</p>}
                  <span className="flex-1" />
                  <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
                    <X />
                    {t("common.cancel")}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={dirty}
                    loading={busy === "split"}
                    title={dirty ? t("viewer.chunkTab.splitDirty") : undefined}
                    onClick={() => {
                      const offset = textRef.current?.selectionStart ?? 0;
                      run("split", () => api.post(`/documents/${docId}/chunks/${active.id}/split`, { offset }), saved);
                    }}
                  >
                    <Scissors />
                    {t("viewer.chunkTab.split")}
                  </Button>
                  <Button
                    size="sm"
                    disabled={!dirty || !form.text.trim()}
                    loading={busy === "save"}
                    onClick={() =>
                      run(
                        "save",
                        () => api.put(`/documents/${docId}/chunks/${active.id}`, { ...form, page_from: null, page_to: null }),
                        saved,
                      )
                    }
                  >
                    <Save />
                    {t("common.save")}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="rounded-lg border border-border bg-card p-4">
                <Markdown text={active.text} />
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
