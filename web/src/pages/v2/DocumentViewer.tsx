/** Chi tiết tài liệu — パイプライン / 原本 / テキスト / インサイト / 検査. Route: /documents/:docId[?page=N&tab=…]
 *  Không có ?tab (vừa upload / bấm từ danh sách 文書): luôn mở パイプライン. */
import { useQueryClient } from "@tanstack/react-query";
import { FileQuestion, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { EmptyState, buttonVariants } from "@/components/ui";
import { ChunksTab } from "@/components/v2/viewer/ChunksTab";
import { InsightsTab } from "@/components/v2/viewer/InsightsTab";
import { InspectTab } from "@/components/v2/viewer/InspectTab";
import { PipelineTab } from "@/components/v2/viewer/PipelineTab";
import { ReviewGate, ReviewPrompt, reviewStage } from "@/components/v2/viewer/ReviewGate";
import { OriginalTab } from "@/components/v2/viewer/OriginalTab";
import { TextTab } from "@/components/v2/viewer/TextTab";
import { TopBar } from "@/components/v2/viewer/TopBar";
import {
  QueryError,
  VIEWER_TABS,
  type ViewerTab,
  isTypingTarget,
  useDocInfo,
  useDocMeta,
  vk,
} from "@/components/v2/viewer/shared";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useEventStream } from "@/lib/sse";
import type { JobEvent } from "@/lib/types";

const DONE_STATUSES = ["indexed", "failed"];
/** Số dòng live log giữ trong bộ nhớ / DOM. Server gửi lại 200 dòng gần nhất khi kết nối. */
const LOG_MAX = 500;
/** Sự kiện chỉ báo tiến độ, không đổi nội dung trang / phần tử / chất lượng. */
const PROGRESS_ONLY = /^(job\.|cu\.started$|chunk\.(rough|round|section)$|index\.progress$)/;

export default function DocumentViewerPage() {
  const { docId = "" } = useParams();
  const { t } = useTranslation();
  const { can } = useAuth();
  const canEdit = can("reviewer");
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();

  const info = useDocInfo(docId);
  const meta = useDocMeta(docId);
  const total = info.data?.pages ?? 0;

  const tabParam = params.get("tab") as ViewerTab | null;
  const tab: ViewerTab = tabParam && VIEWER_TABS.includes(tabParam) ? tabParam : "pipeline";
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
        next.set("tab", k);
        return next;
      },
      { replace: true },
    );
  }, []);

  /** Chunk đang chọn ở tab チャンク (?chunk=) */
  const chunkId = params.get("chunk");
  const onChunk = useCallback((id: string) => {
    setRef.current(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("tab", "chunks");
        next.set("chunk", id);
        return next;
      },
      { replace: true },
    );
  }, []);
  /** Từ tab チャンク sang 原本 / 検査 ở một trang */
  const onGo = useCallback((k: ViewerTab, p: number) => {
    setRef.current(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("tab", k);
        if (p <= 1) next.delete("page");
        else next.set("page", String(p));
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

  // Live: một kết nối SSE cho cả màn (live log của tab パイプライン dùng chung). Sự kiện mới → làm mới dữ liệu,
  // gom lại tối đa ~1 lần / 1.5 s; React Query chỉ tải lại query đang hiển thị, query khác chỉ đánh dấu cũ.
  // Sự kiện tiến độ (job.*, vòng chunk, index.progress…) chỉ làm mới tài liệu (nhẹ); nội dung / chất lượng chỉ tải
  // lại khi có sự kiện làm đổi nội dung — tài liệu lớn không bị tải lại chất lượng mỗi 1.5 s lúc đang index.
  const throttle = useRef<number | undefined>(undefined);
  const contentChanged = useRef(false);
  useEffect(() => () => window.clearTimeout(throttle.current), []);
  const onEvent = useCallback(
    (e: JobEvent) => {
      if (!PROGRESS_ONLY.test(e.code)) contentChanged.current = true;
      if (throttle.current !== undefined) return;
      throttle.current = window.setTimeout(() => {
        throttle.current = undefined;
        qc.invalidateQueries({ queryKey: ["document", docId] });
        if (contentChanged.current) {
          contentChanged.current = false;
          qc.invalidateQueries({ queryKey: vk.all(docId) });
          qc.invalidateQueries({ queryKey: vk.pages(docId) }); // trạng thái duyệt trang (tab 検査)
        }
      }, 1500);
    },
    [qc, docId],
  );
  const { events, connected } = useEventStream(docId ? `/api/stream/documents/${docId}` : null, onEvent, LOG_MAX);

  const notFound = info.error instanceof ApiError && (info.error.status === 404 || info.error.status === 403);
  const processing = !!info.data && !DONE_STATUSES.includes(info.data.status);
  const showInsights = useCallback(() => onTab("insights"), [onTab]);

  return (
    <div className="flex h-full min-h-[32rem] flex-col bg-background">
      <TopBar docId={docId} info={info.data} infoLoading={info.isLoading} tab={tab} onTab={onTab} />

      {/* Dừng ở bước review (warn có cảnh báo / manual): popup hỏi review hay すべて承認 (mỗi bước một lần mỗi phiên) */}
      <ReviewPrompt doc={meta.data} canEdit={canEdit} onTab={onTab} />
      {/* ...và banner ở tab review tương ứng — 検査 cho OCR, チャンク cho chunk */}
      {meta.data &&
        ((tab === "inspect" && reviewStage(meta.data) === "ocr") ||
          (tab === "chunks" && reviewStage(meta.data) === "chunk")) && (
          <ReviewGate doc={meta.data} canEdit={canEdit} variant="strip" />
        )}
      {processing && tab !== "pipeline" && !reviewStage(meta.data) && (
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
              <Link
                to="/documents"
                className={buttonVariants({ variant: "outline", size: "sm" })}
              >
                {t("viewer.top.back")}
              </Link>
            }
          />
        </div>
      ) : info.isError && !info.data ? (
        <div className="flex flex-1 items-center justify-center">
          <QueryError error={info.error} onRetry={() => info.refetch()} />
        </div>
      ) : !info.data ? (
        <div className="flex flex-1 items-center justify-center text-muted-foreground">
          <Loader2 className="size-6 animate-spin" aria-hidden />
        </div>
      ) : tab === "pipeline" ? (
        <PipelineTab docId={docId} onTab={onTab} events={events} connected={connected} maxEvents={LOG_MAX} />
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
      ) : tab === "chunks" ? (
        <ChunksTab docId={docId} canEdit={canEdit} selectedId={chunkId} onSelect={onChunk} onGo={onGo} />
      ) : tab === "insights" ? (
        <InsightsTab docId={docId} canEdit={canEdit} />
      ) : (
        <InspectTab
          docId={docId}
          total={total}
          page={page}
          onPage={onPage}
          onOpenChunk={onChunk}
          canEdit={canEdit}
          zoom={zoom}
          onZoom={setZoom}
        />
      )}
    </div>
  );
}
