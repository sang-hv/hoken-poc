/** Mảnh hiển thị một tài liệu trong danh sách (màn 文書, Dashboard): tên + meta, trạng thái + tiến độ, việc tiếp theo. */
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { buttonVariants } from "@/components/ui";
import { docPageTotal, useDocProgressLabel } from "@/components/docProgress";
import { useAuth } from "@/lib/auth";
import type { Doc, DocStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Tên (link) + một dòng meta: 種別 · 書籍ページ · số trang. Tên file nằm ở tooltip (thường trùng tên). */
export function DocTitle({ doc }: { doc: Doc }) {
  const { t } = useTranslation();
  const total = docPageTotal(doc);
  return (
    <div className="min-w-0">
      <Link
        to={`/documents/${doc.id}`}
        title={doc.filename}
        className={cn("break-words font-medium hover:text-primary", !doc.enabled && "text-muted-foreground")}
      >
        {doc.name}
      </Link>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {t(`kinds.${doc.kind}`, { defaultValue: doc.kind })} ·{" "}
        <span className="tabular-nums">
          {t("documents.bookPages", { from: doc.book_page_start, to: doc.book_page_start + total - 1 })} ·{" "}
          {t("documents.pageCount", { count: total })}
        </span>
        {!doc.enabled && <> · {t("documents.next.excluded")}</>}
      </p>
    </div>
  );
}

export const STATUS_DOT: Record<DocStatus, string> = {
  processing: "bg-info animate-pulse-dot",
  stitching: "bg-info animate-pulse-dot",
  chunking: "bg-info animate-pulse-dot",
  indexing: "bg-info animate-pulse-dot",
  ocr_review: "bg-warning",
  ready_for_chunking: "bg-warning",
  chunk_review: "bg-warning",
  indexed: "bg-success",
  failed: "bg-danger",
};

/** Trạng thái dạng chấm + chữ (bảng nhiều dòng: pill nhiều màu làm rối mắt) + tiến độ của bước hiện tại. */
export function DocState({ doc }: { doc: Doc }) {
  const { t } = useTranslation();
  const label = useDocProgressLabel();
  return (
    <div className="min-w-0">
      <p className="flex items-center gap-2 whitespace-nowrap">
        <span className={cn("size-2 shrink-0 rounded-full", STATUS_DOT[doc.status])} aria-hidden />
        <span className={cn(doc.status === "failed" && "text-danger")}>{t(`docStatus.${doc.status}`)}</span>
      </p>
      {doc.status !== "failed" && (
        <p className="mt-0.5 whitespace-nowrap pl-4 text-xs tabular-nums text-muted-foreground">{label(doc)}</p>
      )}
    </div>
  );
}

/** Việc tiếp theo — chỉ nói hành động (tên bước đã có ở cột 状態), không lặp lại trạng thái. */
export function NextStep({ doc }: { doc: Doc }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const s = doc.stats;
  const base = `/documents/${doc.id}`;
  const failed = s.failed ?? 0;
  const link = (to: string, label: string, danger = false) =>
    can("reviewer") ? (
      <Link
        to={to}
        className={cn(
          buttonVariants({ variant: "outline", size: "sm" }),
          "h-7 shadow-none",
          danger && "border-danger/40 text-danger hover:bg-danger-soft",
        )}
      >
        {label}
      </Link>
    ) : (
      <span className="text-xs text-muted-foreground">{label}</span>
    );

  if (doc.status === "failed") return link(base, t("documents.next.viewError"), true);
  if (failed > 0) return link(base, t("documents.next.failedPages", { n: failed }), true);
  if (doc.status === "ocr_review" && (s.review ?? 0) > 0)
    return link(`${base}/review`, t("documents.next.review", { n: s.review }));
  if (doc.status === "ready_for_chunking") return link(base, t("detail.startChunking"));
  if (doc.status === "chunk_review")
    return link(`${base}?tab=chunks`, t("documents.next.review", { n: (s.chunks ?? 0) - (s.chunks_approved ?? 0) }));
  if (doc.status === "indexed")
    return (
      <span className={cn("text-xs", doc.enabled ? "text-muted-foreground" : "text-warning")}>
        {doc.enabled ? t("documents.next.searchable") : t("documents.next.excluded")}
      </span>
    );
  return <span className="text-xs text-muted-foreground">—</span>;
}

