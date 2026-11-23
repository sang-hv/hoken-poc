/** Ngăn 「原本」 trong tab チャンク (thay popup 原本と比較 cũ): các trang gốc của chunk xếp dọc — chunk trải nhiều
 *  trang vẫn thấy liền mạch — với khung xanh quanh phần tử thuộc chunk. Nằm cạnh nội dung chunk, cả khi đang sửa. */
import { useQuery } from "@tanstack/react-query";
import { ImageOff, ScanText, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Skeleton } from "@/components/ui";
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
        <span className="font-medium tabular-nums">{t("viewer.page.short", { page: page.page })}</span>
        <span className="text-xs text-muted-foreground">{t("viewer.chunkTab.bookPage", { page: page.book_page })} ·</span>
        <span className="text-xs text-muted-foreground">{t("viewer.compare.matched", { n: page.elements.length })}</span>
        <span className="flex-1" />
        <Button variant="ghost" size="sm" className="h-7" onClick={() => onInspect(page.page)}>
          <ScanText />
          {t("viewer.compare.openInspect")}
        </Button>
      </div>
      <div className="relative w-full rounded-md border border-border bg-white">
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

export function ChunkSourcePane({
  docId,
  chunk,
  focus,
  onInspect,
  onClose,
}: {
  docId: string;
  chunk: Chunk;
  /** trang PDF cần cuộn tới; `n` đổi mỗi lần bấm (bấm lại cùng trang vẫn cuộn) */
  focus: { page: number; n: number } | null;
  onInspect: (page: number) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: [...vk.all(docId), "chunk-regions", chunk.id, chunk.updated_at],
    queryFn: () => api.get<ChunkRegions>(`/documents/${docId}/chunks/${chunk.id}/regions`),
  });
  const pane = useRef<HTMLDivElement>(null);
  const go = (p: number) =>
    pane.current?.querySelector(`[data-page="${p}"]`)?.scrollIntoView({ block: "start", behavior: "smooth" });
  useEffect(() => {
    if (q.data && focus) requestAnimationFrame(() => go(focus.page));
  }, [q.data, focus]);
  useEffect(() => {
    if (pane.current) pane.current.scrollTop = 0;
  }, [chunk.id]);
  const pages = q.data?.pages ?? [];

  return (
    <section
      aria-label={t("viewer.chunkTab.source")}
      className="flex min-h-[60vh] min-w-0 flex-col border-t border-border bg-muted/40 lg:min-h-0 lg:border-l lg:border-t-0"
    >
      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-border bg-card px-3 text-xs">
        <span className="mr-1 text-sm font-medium">{t("viewer.chunkTab.source")}</span>
        {pages.length > 1 &&
          pages.map((p) => (
            <Button key={p.page} variant="ghost" size="sm" className="h-7 px-2 tabular-nums" onClick={() => go(p.page)}>
              {t("viewer.page.short", { page: p.page })}
            </Button>
          ))}
        <span className="flex-1" />
        <span className="hidden items-center gap-1.5 text-muted-foreground sm:flex">
          <span className="inline-block size-3 rounded-[2px] border-2 border-info bg-info/10" />
          {t("viewer.compare.full")}
        </span>
        <span className="ml-2 hidden items-center gap-1.5 text-muted-foreground sm:flex">
          <span className="inline-block size-3 rounded-[2px] border-2 border-dashed border-info" />
          {t("viewer.compare.partShort")}
        </span>
        <Button variant="ghost" size="iconSm" className="ml-1" aria-label={t("viewer.chunkTab.sourceHide")} onClick={onClose}>
          <X />
        </Button>
      </div>
      <div ref={pane} className="min-h-0 flex-1 space-y-6 overflow-y-auto p-4">
        {q.isError ? (
          <QueryError error={q.error} onRetry={() => q.refetch()} />
        ) : !q.data ? (
          <Skeleton className="h-[60vh]" />
        ) : pages.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("viewer.compare.none")}</p>
        ) : (
          pages.map((p) => <RegionPage key={p.page} docId={docId} page={p} onInspect={onInspect} />)
        )}
      </div>
    </section>
  );
}
