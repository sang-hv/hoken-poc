import { AlertTriangle, ArrowRight, CheckCircle2, ListChecks, Loader2, UserCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { buttonVariants } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { Doc } from "@/lib/types";
import { cn, pct } from "@/lib/utils";

const RUNNING = new Set(["processing", "stitching", "chunking", "indexing"]);

export function docPageTotal(doc: Doc) {
  return doc.page_to - doc.page_from + 1;
}

/** Tiến độ tổng (0–100): xử lý trang 30% · review OCR 35% · chunk 5% · review chunk 25% · index 5%. */
export function docProgress(doc: Doc) {
  const total = docPageTotal(doc);
  const s = doc.stats;
  if (doc.status === "indexed") return 100;
  if (["chunk_review", "indexing"].includes(doc.status))
    return 70 + Math.round((pct(s.chunks_approved ?? 0, s.chunks ?? 1) * 25) / 100);
  if (["ready_for_chunking", "chunking"].includes(doc.status)) return 65;
  const processed = total - (s.queued ?? 0) - (s.docling ?? 0) - (s.routed ?? 0) - (s.cu ?? 0);
  return Math.round((processed / total) * 30 + ((s.approved ?? 0) / total) * 35);
}

/** Chú thích dưới thanh tiến độ, theo bước hiện tại (trang ở giai đoạn OCR, chunk ở giai đoạn chunk). */
export function useDocProgressLabel() {
  const { t } = useTranslation();
  return (doc: Doc) => {
    const s = doc.stats;
    if (["chunk_review", "indexing"].includes(doc.status))
      return t("documents.chunksApproved", { n: s.chunks_approved ?? 0, total: s.chunks ?? 0 });
    if (doc.status === "indexed") return t("documents.chunksIndexed", { n: s.chunks_indexed ?? s.chunks ?? 0 });
    return t("documents.pagesApproved", { n: s.approved ?? 0, total: docPageTotal(doc) });
  };
}

/** Việc cần làm tiếp với tài liệu — nút đi thẳng tới chỗ cần xử lý. */
export function NextAction({ doc, className }: { doc: Doc; className?: string }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const s = doc.stats;
  const base = `/documents/${doc.id}`;
  const failed = s.failed ?? 0;

  let item: { to?: string; label: string; icon: React.ReactNode; tone: "action" | "danger" | "muted" | "success" };
  if (doc.status === "failed") item = { to: base, label: t("documents.next.viewError"), icon: <AlertTriangle />, tone: "danger" };
  else if (failed > 0)
    item = { to: base, label: t("documents.next.failedPages", { n: failed }), icon: <AlertTriangle />, tone: "danger" };
  else if (doc.status === "ocr_review" && (s.review ?? 0) > 0)
    item = { to: `${base}/review`, label: t("documents.next.reviewOcr", { n: s.review }), icon: <UserCheck />, tone: "action" };
  else if (doc.status === "ready_for_chunking")
    item = { to: base, label: t("detail.startChunking"), icon: <ArrowRight />, tone: "action" };
  else if (doc.status === "chunk_review")
    item = {
      to: `${base}?tab=chunks`,
      label: t("documents.next.reviewChunks", { n: (s.chunks ?? 0) - (s.chunks_approved ?? 0) }),
      icon: <ListChecks />,
      tone: "action",
    };
  else if (doc.status === "indexed")
    item = doc.enabled
      ? { label: t("documents.next.searchable"), icon: <CheckCircle2 />, tone: "success" }
      : { label: t("documents.next.excluded"), icon: <CheckCircle2 />, tone: "muted" };
  else
    item = {
      label: t("detail.stepRunning"),
      icon: RUNNING.has(doc.status) ? <Loader2 className="animate-spin" /> : null,
      tone: "muted",
    };

  if (item.to && can("reviewer") && item.tone !== "muted")
    return (
      <Link
        to={item.to}
        className={cn(
          buttonVariants({ size: "sm", variant: item.tone === "danger" ? "outline" : "soft" }),
          item.tone === "danger" && "border-danger/40 text-danger",
          className,
        )}
      >
        {item.icon}
        {item.label}
      </Link>
    );
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap text-xs [&_svg]:size-3.5",
        item.tone === "success" ? "text-success" : item.tone === "danger" ? "text-danger" : "text-muted-foreground",
        className,
      )}
    >
      {item.icon}
      {item.label}
    </span>
  );
}
