import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, FileX2, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useToastError } from "@/components/common";
import { Button, EmptyState, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ElementDetail } from "./ElementDetail";
import { type ElementFilter, ElementList } from "./ElementList";
import { PageCanvas } from "./PageCanvas";
import { ChunksList, HistoryList, WeakList } from "./PanelLists";
import { type PageMark, PromptDialog, Thumbnails, ZoomControl } from "./parts";
import { QualityBar } from "./QualityBar";
import { GradeChip, type PanelTab, QueryError, useElements, useQuality, useWeak, vk } from "./shared";

const POLL_MS = 60_000;

/** 検査: thanh chất lượng, thumbnail có chấm hạng, ảnh trang + khung phần tử, panel 要素 / チャンク / 弱点 / 修正履歴. */
export function InspectTab({
  docId,
  total,
  page,
  onPage,
  canEdit,
  zoom,
  onZoom,
}: {
  docId: string;
  total: number;
  page: number;
  onPage: (p: number) => void;
  canEdit: boolean;
  zoom: number;
  onZoom: (z: number) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();

  // Sau "弱点をAIで修正" / "このページを再読込": hỏi lại định kỳ một lúc để thấy kết quả chạy nền.
  const [pollUntil, setPollUntil] = useState(0);
  const polling = pollUntil > 0;
  useEffect(() => {
    if (!pollUntil) return;
    const id = window.setTimeout(() => setPollUntil(0), Math.max(0, pollUntil - Date.now()));
    return () => clearTimeout(id);
  }, [pollUntil]);
  const startPolling = () => setPollUntil(Date.now() + POLL_MS);

  const quality = useQuality(docId, polling);
  useWeak(docId, polling); // giữ danh sách điểm yếu mới khi đang chờ AI
  const elements = useElements(docId, page, polling);

  const [panel, setPanel] = useState<PanelTab>("elements");
  const [filter, setFilter] = useState<ElementFilter>("all");
  const [hovered, setHovered] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [pendingSelect, setPendingSelect] = useState<{ page: number; eid: string } | null>(null);
  const [rerunOpen, setRerunOpen] = useState(false);

  // Đổi trang → bỏ chọn, trừ khi đang nhảy tới một phần tử cụ thể (từ tab 弱点).
  useEffect(() => {
    setHovered(null);
    if (pendingSelect && pendingSelect.page === page) {
      setSelected(pendingSelect.eid);
      setPendingSelect(null);
    } else setSelected(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  const openElement = (p: number, eid: string) => {
    setPanel("elements");
    if (p === page) setSelected(eid);
    else {
      setPendingSelect({ page: p, eid });
      onPage(p);
    }
  };

  const marks = useMemo(() => {
    const m: Record<number, PageMark> = {};
    for (const p of quality.data?.pages ?? []) m[p.page] = { grade: p.grade, weak_open: p.weak_open };
    return m;
  }, [quality.data]);

  const data = elements.data;
  const selectedEl = selected ? data?.elements.find((e) => e.id === selected) : undefined;
  const elementsMissing = elements.error instanceof ApiError && elements.error.status === 404;

  const rerunPage = async (prompt: string) => {
    try {
      await api.post(`/documents/${docId}/pages/${page}/rerun`, { prompt });
      toast.success(t("viewer.pageRerun.queued"));
      qc.invalidateQueries({ queryKey: vk.history(docId, page) });
      startPolling();
    } catch (e) {
      toastError(e);
      throw e;
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <QualityBar
        docId={docId}
        quality={quality.data}
        loading={quality.isLoading}
        canEdit={canEdit}
        onGoPage={onPage}
        onShowWeak={() => {
          setPanel("weak");
          setSelected(null);
        }}
        onStartPolling={startPolling}
      />
      {quality.isError && !(quality.error instanceof ApiError && quality.error.status === 404) && (
        <div className="shrink-0 border-b border-border">
          <QueryError error={quality.error} onRetry={() => quality.refetch()} className="py-3" />
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <Thumbnails docId={docId} total={total} current={page} onSelect={onPage} marks={marks} />

        <section className="flex min-h-[55vh] min-w-0 flex-1 flex-col bg-muted/40 md:min-h-0">
          <div className="min-h-0 flex-1 overflow-auto px-6 py-6">
            {total <= 0 ? (
              <EmptyState icon={<FileX2 />} title={t("viewer.page.none")} />
            ) : (
              <PageCanvas
                docId={docId}
                page={page}
                data={data}
                zoom={zoom}
                hovered={hovered}
                selected={selected}
                onHover={setHovered}
                onSelect={(id) => {
                  setPanel("elements");
                  setSelected(id);
                }}
              />
            )}
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-border bg-card px-3 py-2">
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="iconSm"
                disabled={page <= 1}
                onClick={() => onPage(page - 1)}
                aria-label={t("viewer.page.prev")}
              >
                <ChevronLeft />
              </Button>
              <span className="min-w-24 text-center text-sm font-medium tabular-nums">
                {total > 0 ? t("viewer.page.of", { page, total }) : "—"}
              </span>
              <Button
                variant="ghost"
                size="iconSm"
                disabled={page >= total}
                onClick={() => onPage(page + 1)}
                aria-label={t("viewer.page.next")}
              >
                <ChevronRight />
              </Button>
            </div>
            {data ? (
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                {t("viewer.quality.pageGrade")}
                <GradeChip grade={data.grade} score={data.score} />
              </span>
            ) : elements.isLoading ? (
              <Skeleton className="h-5 w-28" />
            ) : null}
            <div className="flex-1" />
            <span className="hidden text-[11px] text-muted-foreground xl:inline">{t("viewer.page.keys")}</span>
            <ZoomControl zoom={zoom} onZoom={onZoom} />
            {canEdit && total > 0 && (
              <Button variant="outline" size="sm" onClick={() => setRerunOpen(true)}>
                <RefreshCw className={cn(polling && "animate-spin")} />
                {t("viewer.pageRerun.button")}
              </Button>
            )}
          </div>
        </section>

        <aside className="flex min-h-[60vh] w-full shrink-0 flex-col border-t border-border bg-card md:min-h-0 md:w-[22rem] md:border-l md:border-t-0 xl:w-[26rem]">
          <Tabs value={panel} onValueChange={(v) => setPanel(v as PanelTab)} className="flex min-h-0 flex-1 flex-col">
            <div className="shrink-0 border-b border-border px-3 py-2">
              <TabsList className="grid w-full grid-cols-4">
                {(["elements", "chunks", "weak", "history"] as PanelTab[]).map((k) => (
                  <TabsTrigger key={k} value={k} className="justify-center px-1.5 text-xs">
                    {t(`viewer.panel.${k}`)}
                    {k === "weak" && (quality.data?.weak_open ?? 0) > 0 && (
                      <span className="rounded-full bg-danger px-1.5 text-[10px] font-semibold leading-4 text-white tabular-nums">
                        {quality.data!.weak_open}
                      </span>
                    )}
                  </TabsTrigger>
                ))}
              </TabsList>
            </div>

            <TabsContent value="elements" className="flex min-h-0 flex-1 flex-col data-[state=inactive]:hidden">
              {elements.isLoading ? (
                <div className="space-y-2 p-4">
                  {Array.from({ length: 6 }, (_, i) => (
                    <Skeleton key={i} className="h-16" />
                  ))}
                </div>
              ) : elements.isError ? (
                elementsMissing ? (
                  <EmptyState title={t("viewer.state.processing")} hint={t("viewer.state.processingHint")} />
                ) : (
                  <QueryError error={elements.error} onRetry={() => elements.refetch()} />
                )
              ) : selected ? (
                <ElementDetail
                  docId={docId}
                  page={page}
                  el={selectedEl}
                  canEdit={canEdit}
                  onBack={() => setSelected(null)}
                />
              ) : (
                <ElementList
                  elements={data?.elements ?? []}
                  filter={filter}
                  onFilter={setFilter}
                  hovered={hovered}
                  onHover={setHovered}
                  onSelect={setSelected}
                />
              )}
            </TabsContent>
            <TabsContent value="chunks" className="min-h-0 flex-1 overflow-y-auto data-[state=inactive]:hidden">
              <ChunksList docId={docId} page={page} />
            </TabsContent>
            <TabsContent value="weak" className="min-h-0 flex-1 overflow-y-auto data-[state=inactive]:hidden">
              <WeakList docId={docId} onOpen={openElement} />
            </TabsContent>
            <TabsContent value="history" className="min-h-0 flex-1 overflow-y-auto data-[state=inactive]:hidden">
              <HistoryList docId={docId} page={page} onOpen={(eid) => openElement(page, eid)} />
            </TabsContent>
          </Tabs>
        </aside>
      </div>

      <PromptDialog
        open={rerunOpen}
        onOpenChange={setRerunOpen}
        title={t("viewer.pageRerun.title")}
        description={t("viewer.pageRerun.desc")}
        onRun={rerunPage}
      />
    </div>
  );
}
