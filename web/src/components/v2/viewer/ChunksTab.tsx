/** Tab チャンク (cấp tài liệu): danh sách chunk (phân trang ở server + danh sách ảo — chịu được hàng nghìn chunk),
 *  dải trang (chunk có thể trải nhiều trang), điểm, vi phạm luật, ⚠ khi trang của chunk còn điểm yếu. Sửa / tách /
 *  gộp với chunk sau; tài liệu tự chạy → lưu xong tự duyệt + index lại (backend).
 *  Bố cục: danh sách | nội dung chunk | ngăn 原本 (bật/tắt). Thanh thao tác luôn ở trên — kể cả khi đang sửa.
 *  Phím: J / K = chunk sau / trước trong danh sách, Ctrl/⌘+Enter = 承認して次へ (khi đang ở チャンクレビュー).
 *  Route: /documents/:docId?tab=chunks&chunk=<id> */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Columns2, Layers, Loader2, Merge, Pencil, Save, Scissors, Search, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Markdown, useToastError } from "@/components/common";
import { Button, EmptyState, Field, FilterChips, Input, Kbd, Skeleton, Textarea, Tip } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useDebounced } from "@/lib/hooks";
import type { Chunk, Doc } from "@/lib/types";
import type { ChunkListPage, ChunkSummary } from "@/lib/v2types";
import { cn } from "@/lib/utils";
import {
  BLOCK,
  type ChunkFilter,
  ChunkList,
  type ChunkListParams,
  ck,
  confidenceClass,
  listUrl,
  useChunkHead,
  useChunkIndex,
} from "./ChunkList";
import { ChunkSourcePane } from "./ChunkSourcePane";
import { reviewStage } from "./ReviewGate";
import { QueryError, type ViewerTab, bookToPdf, isTypingTarget, useDocMeta, useQuality, vk } from "./shared";

/** Một mục trong dải thông số của chunk (nhãn nhỏ ở trên, giá trị ở dưới). */
function Stat({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm tabular-nums">{children}</dd>
    </div>
  );
}

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
  /** Ngăn 原本: mặc định mở trên màn rộng (so với bản gốc là việc chính khi review chunk) */
  const [source, setSource] = useState(() => typeof window !== "undefined" && window.innerWidth >= 1280);
  const [focusPage, setFocusPage] = useState<{ page: number; n: number } | null>(null);
  const showPage = (page: number) => {
    setSource(true);
    setFocusPage((f) => ({ page, n: (f?.n ?? 0) + 1 }));
  };

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
      return true;
    } catch (e) {
      toastError(e);
      return false;
    } finally {
      setBusy(null);
    }
  };
  // Tự index lại sau khi sửa: tài liệu tự chạy và không đang dừng ở チャンクレビュー (cùng điều kiện với backend)
  const autoIndex = !!d?.auto_review && d?.review_hold !== "chunk";
  const saved = autoIndex ? t("viewer.chunkTab.savedReindex") : t("common.saved");

  /** Sang chunk cách `delta` dòng trong danh sách đang lọc (dùng khối đã tải nếu có, không thì hỏi đúng 1 dòng). */
  const index = focusIndex.data ?? null;
  const goRel = useCallback(
    async (delta: number) => {
      if (index === null || index < 0) return;
      const j = index + delta;
      if (j < 0 || j >= total) return;
      const cached = qc.getQueryData<ChunkListPage>(ck.block(docId, params, Math.floor(j / BLOCK)));
      let id = cached?.items[j % BLOCK]?.id;
      if (!id) {
        try {
          id = (await api.get<ChunkListPage>(listUrl(docId, params, j, 1))).items[0]?.id;
        } catch (e) {
          toastError(e);
        }
      }
      if (id) onSelect(id);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [index, total, docId, params.filter, params.q, params.page, onSelect],
  );
  const approveNext = async () => {
    if (!active) return;
    if (active.status === "draft") {
      const ok = await run("approve", () =>
        api.post(`/documents/${docId}/chunks/approve`, { ids: [active.id], approved: true }),
      );
      if (!ok) return;
    }
    goRel(1);
  };
  const keys = useRef({ goRel, approveNext, editing, reviewing, editable });
  keys.current = { goRel, approveNext, editing, reviewing, editable };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const k = keys.current;
      if (e.defaultPrevented || k.editing || isTypingTarget(e.target)) return;
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && k.reviewing && k.editable) {
        e.preventDefault();
        k.approveNext();
      } else if (!e.ctrlKey && !e.metaKey && !e.altKey && (e.key === "j" || e.key === "k")) {
        e.preventDefault();
        k.goRel(e.key === "j" ? 1 : -1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
  // Ngăn 原本 đang mở → cột giữa hẹp: nút phụ chỉ còn icon (có aria-label + title) dưới 2xl
  const label = source ? "hidden 2xl:inline" : "hidden sm:inline";
  const needsCheck = !!active && (active.violations.length > 0 || activeWeak.length > 0);

  return (
    <div
      className={cn(
        "grid min-h-0 flex-1 grid-cols-1",
        source ? "lg:grid-cols-[22rem_minmax(0,1fr)_minmax(0,1fr)]" : "lg:grid-cols-[22rem_minmax(0,1fr)]",
      )}
    >
      {/* ------------------------------------------------ danh sách */}
      <aside className="flex max-h-[45vh] min-h-0 flex-col border-b border-border bg-card lg:max-h-none lg:border-b-0 lg:border-r">
        <div className="flex flex-col gap-2.5 border-b border-border p-3">
          <div className="flex gap-2">
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("viewer.chunkTab.search")}
                aria-label={t("viewer.chunkTab.search")}
                className="h-8 pl-8 text-sm shadow-none"
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
              className="h-8 w-24 text-sm shadow-none"
            />
          </div>
          <div className="flex items-center gap-1">
            <FilterChips
              label={t("viewer.chunkTab.filterLabel")}
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: t("viewer.chunkTab.filterAll"), count: counts.all },
                { value: "issues", label: t("viewer.chunkTab.filterIssues"), count: counts.issues, tone: "warning" },
              ]}
            />
            <span className="flex-1" />
            {(q || pageNum) && (
              <span className="text-xs text-muted-foreground">{t("viewer.chunkTab.matches", { n: total })}</span>
            )}
          </div>
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
        <p className="hidden shrink-0 items-center gap-1.5 border-t border-border px-4 py-2 text-xs text-muted-foreground lg:flex">
          <Kbd>J</Kbd>
          <Kbd>K</Kbd>
          {t("viewer.chunkTab.keysMove")}
          {reviewing && editable && (
            <>
              <span className="mx-1">·</span>
              <Kbd>Ctrl/⌘ Enter</Kbd>
              {t("viewer.chunkTab.approveNext")}
            </>
          )}
        </p>
      </aside>

      {/* ------------------------------------------------ chi tiết */}
      <section className="flex min-h-0 min-w-0 flex-col">
        {active && (
          <>
            <div className="flex min-h-11 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-card px-4 py-1.5">
              <h2 className="flex min-w-0 flex-1 items-baseline gap-2 text-sm">
                <span className="shrink-0 tabular-nums text-muted-foreground">#{active.seq}</span>
                {active.item_code && <span className="shrink-0 font-mono font-semibold">{active.item_code}</span>}
                <span className="truncate font-medium">{active.title}</span>
              </h2>
              {editing ? (
                <div className="flex items-center gap-1.5">
                  <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
                    <X />
                    {t("common.cancel")}
                  </Button>
                  <Tip content={dirty ? t("viewer.chunkTab.splitDirty") : t("viewer.chunkTab.splitHint")}>
                    <Button
                      variant="outline"
                      size="sm"
                      className="shadow-none"
                      disabled={dirty}
                      loading={busy === "split"}
                      onClick={() => {
                        const offset = textRef.current?.selectionStart ?? 0;
                        run("split", () => api.post(`/documents/${docId}/chunks/${active.id}/split`, { offset }), saved);
                      }}
                    >
                      <Scissors />
                      {t("viewer.chunkTab.split")}
                    </Button>
                  </Tip>
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
              ) : (
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-pressed={source}
                    aria-label={t("viewer.chunkTab.source")}
                    title={t("viewer.chunkTab.source")}
                    className={cn(source && "bg-accent")}
                    onClick={() => setSource((v) => !v)}
                  >
                    <Columns2 />
                    <span className={label}>{t("viewer.chunkTab.source")}</span>
                  </Button>
                  {editable && (
                    <>
                      <Button variant="ghost" size="sm" aria-label={t("viewer.chunkTab.edit")} title={t("viewer.chunkTab.edit")} onClick={() => setEditing(true)}>
                        <Pencil />
                        <span className={label}>{t("viewer.chunkTab.edit")}</span>
                      </Button>
                      {next && (
                        <Tip content={t("viewer.chunkTab.mergeTip", { seq: next.seq })}>
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-label={t("viewer.chunkTab.mergeNext")}
                            loading={busy === "merge"}
                            onClick={() =>
                              run(
                                "merge",
                                () => api.post(`/documents/${docId}/chunks/merge`, { ids: [active.id, next.id] }),
                                saved,
                              )
                            }
                          >
                            {busy !== "merge" && <Merge />}
                            <span className={label}>{t("viewer.chunkTab.mergeNext")}</span>
                          </Button>
                        </Tip>
                      )}
                      {reviewing &&
                        (active.status === "draft" ? (
                          <Tip content={t("viewer.approval.shortcut")}>
                            <Button size="sm" className="ml-1" loading={busy === "approve"} onClick={approveNext}>
                              <Check />
                              {t("viewer.chunkTab.approveNext")}
                            </Button>
                          </Tip>
                        ) : (
                          <Button
                            variant="ghost"
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
                    </>
                  )}
                </div>
              )}
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto">
              <div className="flex flex-col gap-5 px-6 py-5">
                <dl className="flex flex-wrap gap-x-8 gap-y-3">
                  {/* Chỉ hiện confidence; hai điểm thành phần (luật / LLM) để trong tooltip */}
                  <Stat label={t("viewer.chunkTab.confidence")}>
                    <Tip
                      content={[
                        `${t("chunks.rules")} ${Math.round(active.rule_score * 100)}%`,
                        active.llm_score !== null ? `${t("chunks.llm")} ${Math.round(active.llm_score * 100)}%` : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    >
                      <span
                        className={cn(
                          "cursor-help",
                          confidenceClass(active.confidence),
                          active.confidence >= 0.7 && "text-foreground",
                        )}
                      >
                        {Math.round(active.confidence * 100)}%
                      </span>
                    </Tip>
                  </Stat>
                  <Stat label={t("viewer.chunkTab.state")}>
                    <span className={cn("inline-flex items-center gap-1", active.status !== "draft" && "text-success")}>
                      {active.status !== "draft" && <Check className="size-3.5" aria-hidden />}
                      {t(`viewer.chunkTab.status.${active.status}`)}
                    </span>
                  </Stat>
                  <Stat label={t("viewer.chunkTab.pages")}>
                    <span className="flex flex-wrap items-baseline gap-x-1.5">
                      {Array.from({ length: pb - pa + 1 }, (_, i) => pa + i).map((p) => (
                        <Tip key={p} content={t("viewer.chunkTab.comparePage", { page: p })}>
                          <button
                            type="button"
                            onClick={() => showPage(p)}
                            className={cn(
                              "cursor-pointer underline decoration-border underline-offset-4 hover:decoration-current",
                              weakPages.has(p) && "text-warning",
                            )}
                          >
                            {t("viewer.page.short", { page: p })}
                          </button>
                        </Tip>
                      ))}
                      <span className="text-xs text-muted-foreground">
                        {t("viewer.chunkTab.bookPages", { from: active.page_from, to: active.page_to })}
                      </span>
                    </span>
                  </Stat>
                  {active.edited_by && active.edited_by !== "auto" && (
                    <Stat label={t("viewer.chunkTab.editor")}>{active.edited_by}</Stat>
                  )}
                </dl>

                {needsCheck && (
                  <div className="border-l-2 border-warning pl-3 text-sm">
                    <p className="font-medium">{t("viewer.chunkTab.toCheck")}</p>
                    <ul className="mt-1 space-y-0.5 text-muted-foreground">
                      {active.violations.map((v) => (
                        <li key={v}>
                          {t("chunks.violations")}: {t(`violations.${v}`, { defaultValue: v })}
                        </li>
                      ))}
                      {activeWeak.length > 0 && (
                        <li>
                          {t("viewer.chunkTab.weakHint", { pages: activeWeak.map((p) => `p.${p}`).join(", ") })}{" "}
                          <button
                            type="button"
                            onClick={() => onGo("inspect", activeWeak[0])}
                            className="cursor-pointer font-medium text-primary hover:underline"
                          >
                            {t("viewer.compare.openInspect")}
                          </button>
                        </li>
                      )}
                    </ul>
                  </div>
                )}
                {canEdit && !editable && (
                  <p className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" />
                    {t("viewer.chunkTab.busy")}
                  </p>
                )}

                {editing ? (
                  <div className="flex flex-col gap-3">
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-[12rem_1fr]">
                      <Field label={t("chunks.itemCode")}>
                        <Input
                          className="font-mono shadow-none"
                          value={form.item_code}
                          onChange={(e) => setForm({ ...form, item_code: e.target.value })}
                        />
                      </Field>
                      <Field label={t("chunks.titleField")}>
                        <Input
                          className="shadow-none"
                          value={form.title}
                          onChange={(e) => setForm({ ...form, title: e.target.value })}
                        />
                      </Field>
                    </div>
                    <div className={cn("grid grid-cols-1 gap-3", !source && "xl:grid-cols-2")}>
                      <Field label={t("chunks.text")} hint={autoIndex ? t("viewer.chunkTab.autoNote") : undefined}>
                        <Textarea
                          ref={textRef}
                          rows={22}
                          className="font-mono text-dense shadow-none"
                          value={form.text}
                          onChange={(e) => setForm({ ...form, text: e.target.value })}
                        />
                      </Field>
                      {!source && (
                        <Field label={t("review.preview")}>
                          <div className="h-full max-h-[34rem] overflow-auto rounded-lg border border-border p-4">
                            <Markdown text={form.text} />
                          </div>
                        </Field>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="max-w-3xl border-t border-border pt-5">
                    <Markdown text={active.text} className="text-reading" />
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </section>

      {active && source && (
        <ChunkSourcePane
          docId={docId}
          chunk={active}
          focus={focusPage}
          onInspect={(p) => onGo("inspect", p)}
          onClose={() => setSource(false)}
        />
      )}
    </div>
  );
}
