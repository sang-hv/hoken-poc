/** Chi tiết nguồn — 原本 / テキスト / インサイト / 検査 (frontend B2). Route: /notebooks/:nbId/sources/:docId[?page=N&tab=…] */
import { useQueryClient } from "@tanstack/react-query";
import { FileQuestion, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { EmptyState, buttonVariants } from "@/components/ui";
import { InsightsTab } from "@/components/v2/viewer/InsightsTab";
import { InspectTab } from "@/components/v2/viewer/InspectTab";
import { OriginalTab } from "@/components/v2/viewer/OriginalTab";
import { TextTab } from "@/components/v2/viewer/TextTab";
import { TopBar } from "@/components/v2/viewer/TopBar";
import {
  QueryError,
  VIEWER_TABS,
  type ViewerTab,
  isTypingTarget,
  useDocInfo,
  useDocPages,
  vk,
} from "@/components/v2/viewer/shared";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useEventStream } from "@/lib/sse";
import type { JobEvent } from "@/lib/types";

const DONE_STATUSES = ["indexed", "failed"];

export default function DocumentViewerPage() {
  const { nbId = "", docId = "" } = useParams();
  const { t } = useTranslation();
  const { can } = useAuth();
  const canEdit = can("reviewer");
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();

  const info = useDocInfo(docId);
  const pages = useDocPages(docId);
  const total = info.data?.pages || pages.data?.length || 0;

  const tabParam = params.get("tab") as ViewerTab | null;
  const tab: ViewerTab = tabParam && VIEWER_TABS.includes(tabParam) ? tabParam : "original";
  const rawPage = Number(params.get("page") ?? "1");
  const page = Math.min(Math.max(1, Number.isFinite(rawPage) ? Math.floor(rawPage) : 1), Math.max(1, total));

  // setSearchParams đổi danh tính theo URL → giữ ref để onPage ổn định (OriginalTab dùng nó trong observer).
  const setRef = useRef(setParams);
  setRef.current = setParams;
  const onPage = useCallback((p: number) => {
    setRef.current(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (p <= 1) next.delete("page");
        else next.set("page", String(p));
        return next;
      },
      { replace: true },
    );
  }, []);
  const onTab = useCallback((k: ViewerTab) => {
    setRef.current(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (k === "original") next.delete("tab");
        else next.set("tab", k);
        return next;
      },
      { replace: true },
    );
  }, []);

  const [zoom, setZoom] = useState(100);

  // ←/→ đổi trang ở 原本 / 検査 (không khi đang gõ hay đang mở hộp thoại).
  const pageRef = useRef({ page, total, tab });
  pageRef.current = { page, total, tab };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const cur = pageRef.current;
      if (cur.tab !== "original" && cur.tab !== "inspect") return;
      if (isTypingTarget(e.target)) return;
      const next = cur.page + (e.key === "ArrowRight" ? 1 : -1);
      if (next < 1 || next > cur.total) return;
      e.preventDefault();
      onPage(next);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onPage]);

  // Live: pipeline / AI ghi kết quả → làm mới dữ liệu của màn (gom lại, tối đa ~1 lần / 1.5 s).
  const throttle = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(throttle.current), []);
  const onEvent = useCallback(
    (_e: JobEvent) => {
      if (throttle.current !== undefined) return;
      throttle.current = window.setTimeout(() => {
        throttle.current = undefined;
        qc.invalidateQueries({ queryKey: vk.all(docId) });
        qc.invalidateQueries({ queryKey: vk.pages(docId) });
      }, 1500);
    },
    [qc, docId],
  );
  useEventStream(docId ? `/api/stream/documents/${docId}` : null, onEvent, 20);

  const notFound = info.error instanceof ApiError && (info.error.status === 404 || info.error.status === 403);
  const processing = !!info.data && !DONE_STATUSES.includes(info.data.status);
  const showInsights = useCallback(() => onTab("insights"), [onTab]);

  return (
    <div className="flex h-full min-h-[32rem] flex-col bg-background">
      <TopBar nbId={nbId} docId={docId} info={info.data} infoLoading={info.isLoading} tab={tab} onTab={onTab} page={page} />

      {processing && (
        <div role="status" className="flex shrink-0 items-center gap-2 border-b border-border bg-info-soft px-4 py-1.5 text-xs text-info">
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
          <span className="font-medium">{t("viewer.state.processing")}</span>
          <span className="text-info/80">{t("viewer.state.processingHint")}</span>
        </div>
      )}

      {notFound ? (
        <div className="flex flex-1 items-center justify-center">
          <EmptyState
            icon={<FileQuestion />}
            title={t("viewer.state.notFound")}
            hint={t("viewer.state.notFoundHint")}
            action={
              <Link to={`/notebooks/${nbId}`} className={buttonVariants({ variant: "outline", size: "sm" })}>
                {t("viewer.top.back")}
              </Link>
            }
          />
        </div>
      ) : info.isError && !info.data ? (
        <div className="flex flex-1 items-center justify-center">
          <QueryError error={info.error} onRetry={() => info.refetch()} />
        </div>
      ) : tab === "original" ? (
        <OriginalTab
          docId={docId}
          info={info.data}
          infoLoading={info.isLoading}
          total={total}
          page={page}
          onPage={onPage}
          onShowInsights={showInsights}
          zoom={zoom}
          onZoom={setZoom}
        />
      ) : tab === "text" ? (
        <TextTab docId={docId} info={info.data} infoLoading={info.isLoading} page={page} onShowInsights={showInsights} />
      ) : tab === "insights" ? (
        <InsightsTab docId={docId} canEdit={canEdit} />
      ) : (
        <InspectTab docId={docId} total={total} page={page} onPage={onPage} canEdit={canEdit} zoom={zoom} onZoom={setZoom} />
      )}
    </div>
  );
}
