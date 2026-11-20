import { FileX2, ImageOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { EmptyState, Skeleton } from "@/components/ui";
import type { DocInfo } from "@/lib/v2types";
import { InfoPanel } from "./InfoPanel";
import { PageJump, Thumbnails, ZoomControl } from "./parts";
import { pageImageUrl } from "./shared";

function StackedPage({ docId, page, zoom }: { docId: string; page: number; zoom: number }) {
  const { t } = useTranslation();
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <figure data-page={page} className="mx-auto flex scroll-mt-4 flex-col items-center gap-1.5" style={{ width: `${zoom}%` }}>
      <div className="relative w-full overflow-hidden rounded-md border border-border bg-white shadow-card">
        {!loaded && !failed && <Skeleton className="aspect-[1/1.414] w-full rounded-none" />}
        {failed ? (
          <div className="flex aspect-[1/1.414] w-full flex-col items-center justify-center gap-2 bg-muted text-sm text-muted-foreground">
            <ImageOff className="size-6" aria-hidden />
            {t("viewer.page.imageError")}
          </div>
        ) : (
          <img
            src={pageImageUrl(docId, page)}
            alt={t("viewer.page.alt", { page })}
            loading="lazy"
            onLoad={() => setLoaded(true)}
            onError={() => setFailed(true)}
            className={loaded ? "block w-full" : "absolute inset-0 w-full opacity-0"}
          />
        )}
      </div>
      <figcaption className="text-xs tabular-nums text-muted-foreground">{t("viewer.page.short", { page })}</figcaption>
    </figure>
  );
}

/** 原本: thumbnail trái, các trang xếp dọc ở giữa (zoom), panel 情報 bên phải. */
export function OriginalTab({
  docId,
  info,
  infoLoading,
  total,
  page,
  onPage,
  onShowInsights,
  zoom,
  onZoom,
}: {
  docId: string;
  info?: DocInfo;
  infoLoading: boolean;
  total: number;
  page: number;
  onPage: (p: number) => void;
  onShowInsights: () => void;
  zoom: number;
  onZoom: (z: number) => void;
}) {
  const { t } = useTranslation();
  const scroller = useRef<HTMLDivElement>(null);
  const fromScroll = useRef<number | null>(null); // trang vừa được đặt do người dùng cuộn → không cuộn lại
  const lockUntil = useRef(0); // bỏ qua observer ngay sau khi cuộn bằng code

  // Đổi trang từ ngoài (thumbnail, phím, URL) → cuộn tới trang đó.
  useEffect(() => {
    const byScroll = fromScroll.current === page;
    fromScroll.current = null; // dùng một lần
    if (byScroll) return;
    const el = scroller.current?.querySelector(`[data-page="${page}"]`);
    if (el) {
      lockUntil.current = Date.now() + 400;
      el.scrollIntoView({ block: "start" });
    }
  }, [page, total]);

  // Người dùng cuộn → trang hiện nhiều nhất là trang hiện tại.
  useEffect(() => {
    const root = scroller.current;
    if (!root || total <= 0) return;
    const ratios = new Map<number, number>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) ratios.set(Number((e.target as HTMLElement).dataset.page), e.intersectionRatio);
        if (Date.now() < lockUntil.current) return;
        let best = 0;
        let bestRatio = 0;
        for (const [p, r] of ratios)
          if (r > bestRatio || (r === bestRatio && r > 0 && p < best)) {
            best = p;
            bestRatio = r;
          }
        if (best > 0) {
          fromScroll.current = best;
          onPage(best);
        }
      },
      { root, threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] },
    );
    root.querySelectorAll("[data-page]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [total, zoom, onPage]);

  const go = (p: number) => {
    fromScroll.current = null;
    onPage(p);
  };

  return (
    <div className="flex min-h-0 flex-1">
      <Thumbnails docId={docId} total={total} current={page} onSelect={go} />
      <section className="flex min-w-0 flex-1 flex-col bg-muted/40">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border bg-card/80 px-3">
          <div className="md:hidden">
            <PageJump page={page} total={total} onPage={go} />
          </div>
          <span className="hidden text-xs text-muted-foreground md:inline">{total > 0 && t("viewer.page.of", { page, total })}</span>
          <div className="flex-1" />
          <span className="hidden text-[11px] text-muted-foreground lg:inline">{t("viewer.page.keys")}</span>
          <ZoomControl zoom={zoom} onZoom={onZoom} />
        </div>
        <div ref={scroller} className="min-h-0 flex-1 overflow-auto px-4 py-6">
          {total <= 0 ? (
            <EmptyState icon={<FileX2 />} title={t("viewer.page.none")} />
          ) : (
            <div className="flex flex-col gap-6">
              {Array.from({ length: total }, (_, i) => (
                <StackedPage key={i + 1} docId={docId} page={i + 1} zoom={zoom} />
              ))}
            </div>
          )}
        </div>
      </section>
      <InfoPanel docId={docId} info={info} loading={infoLoading} onShowInsights={onShowInsights} />
    </div>
  );
}
