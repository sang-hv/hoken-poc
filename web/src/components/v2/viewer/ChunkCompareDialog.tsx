/** Popup 「原本と比較」 của tab チャンク: trái = nội dung chunk, phải = các trang gốc của chunk (xếp dọc — chunk
 *  trải nhiều trang vẫn thấy liền mạch) với khung xanh quanh phần tử thuộc chunk. Người dùng ở lại chunk đang xem. */
import { useQuery } from "@tanstack/react-query";
import { ImageOff, ScanText } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Markdown } from "@/components/common";
import { Badge, Button, Dialog, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { Chunk } from "@/lib/types";
import type { ChunkRegions } from "@/lib/v2types";
import { cn } from "@/lib/utils";
import { QueryError, pageImageUrl, vk } from "./shared";

const FULL = 0.8; // = rules.COVER_FULL

function RegionPage({
  docId,
  page,
  onInspect,
}: {
  docId: string;
  page: ChunkRegions["pages"][number];
  onInspect: (p: number) => void;
}) {
  const { t } = useTranslation();
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const size = page.image_size;
  const aspect = size && size[0] > 0 && size[1] > 0 ? `${size[0]} / ${size[1]}` : "1 / 1.414";
  return (
    <section data-page={page.page} className="scroll-mt-2">
      <div className="mb-1.5 flex items-center gap-2 text-sm">
        <span className="font-semibold">p.{page.page}</span>
        <span className="text-xs text-muted-foreground">{t("viewer.chunkTab.bookPage", { page: page.book_page })}</span>
        <span className="text-xs text-muted-foreground">· {t("viewer.compare.matched", { n: page.elements.length })}</span>
        <span className="flex-1" />
        <Button variant="ghost" size="sm" className="h-7" onClick={() => onInspect(page.page)}>
          <ScanText />
          {t("viewer.compare.openInspect")}
        </Button>
      </div>
      <div className="relative w-full rounded-md border border-border bg-white shadow-card">
        {!loaded && !failed && <div className="w-full animate-pulse rounded-md bg-muted" style={{ aspectRatio: aspect }} />}
        {failed ? (
          <div
            className="flex w-full items-center justify-center gap-2 rounded-md bg-muted text-sm text-muted-foreground"
            style={{ aspectRatio: aspect }}
          >
            <ImageOff className="size-5" />
            {t("viewer.page.imageError")}
          </div>
        ) : (
          <img
            src={pageImageUrl(docId, page.page)}
            alt={t("viewer.page.alt", { page: page.page })}
            onLoad={() => setLoaded(true)}
            onError={() => setFailed(true)}
            className={cn("block w-full rounded-md", !loaded && "absolute inset-0 opacity-0")}
          />
        )}
        {loaded &&
          page.elements.map((e) => {
            const [x0, y0, x1, y1] = e.bbox;
            const full = e.coverage >= FULL;
            return (
              <span
                key={e.id}
                title={full ? t("viewer.compare.full") : t("viewer.compare.part", { pct: Math.round(e.coverage * 100) })}
                className={cn(
                  "absolute rounded-[3px] border-2 border-info",
                  full ? "bg-info/10" : "border-dashed bg-info/5",
                )}
                style={{
                  left: `${x0 * 100}%`,
                  top: `${y0 * 100}%`,
                  width: `${Math.max(0.5, (x1 - x0) * 100)}%`,
                  height: `${Math.max(0.5, (y1 - y0) * 100)}%`,
                }}
              />
            );
          })}
      </div>
    </section>
  );
}

export function ChunkCompareDialog({
  docId,
  chunk,
  open,
  onOpenChange,
  startPage,
  onInspect,
}: {
  docId: string;
  chunk: Chunk;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  /** trang PDF cuộn tới khi mở */
  startPage: number | null;
  onInspect: (page: number) => void;
}) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: [...vk.all(docId), "chunk-regions", chunk.id, chunk.updated_at],
    queryFn: () => api.get<ChunkRegions>(`/documents/${docId}/chunks/${chunk.id}/regions`),
    enabled: open,
  });
  const pane = useRef<HTMLDivElement>(null);
  const go = (p: number) =>
    pane.current?.querySelector(`[data-page="${p}"]`)?.scrollIntoView({ block: "start", behavior: "smooth" });
  useEffect(() => {
    if (open && q.data && startPage) requestAnimationFrame(() => go(startPage));
  }, [open, q.data, startPage]);
  const pages = q.data?.pages ?? [];

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={
        <span className="flex flex-wrap items-center gap-2">
          {t("viewer.compare.title")}
          <span className="font-mono text-sm text-muted-foreground">#{chunk.seq}</span>
          <Badge tone="primary" className="font-mono">
            {chunk.item_code || "—"}
          </Badge>
        </span>
      }
      description={t("viewer.compare.desc")}
      className="max-w-[min(96vw,1400px)]"
    >
      <div className="-mx-6 -my-5 grid h-[calc(90vh-6rem)] grid-cols-1 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="min-h-0 overflow-y-auto border-b border-border p-5 md:border-b-0 md:border-r">
          {chunk.title && <p className="mb-2 text-sm font-semibold">{chunk.title}</p>}
          <Markdown text={chunk.text} />
        </div>
        <div className="flex min-h-0 flex-col bg-muted/40">
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2 text-xs">
            {pages.length > 1 &&
              pages.map((p) => (
                <Button key={p.page} variant="outline" size="sm" className="h-7" onClick={() => go(p.page)}>
                  p.{p.page}
                </Button>
              ))}
            <span className="flex-1" />
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className="inline-block size-3 rounded-[2px] border-2 border-info bg-info/10" />
              {t("viewer.compare.full")}
            </span>
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className="inline-block size-3 rounded-[2px] border-2 border-dashed border-info" />
              {t("viewer.compare.partShort")}
            </span>
          </div>
          <div ref={pane} className="min-h-0 flex-1 space-y-6 overflow-y-auto p-4">
            {q.isError ? (
              <QueryError error={q.error} onRetry={() => q.refetch()} />
            ) : !q.data ? (
              <Skeleton className="h-[70vh]" />
            ) : pages.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("viewer.compare.none")}</p>
            ) : (
              pages.map((p) => <RegionPage key={p.page} docId={docId} page={p} onInspect={onInspect} />)
            )}
          </div>
        </div>
      </div>
    </Dialog>
  );
}
