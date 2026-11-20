/** Nhắc review khi tài liệu (duyệt tay) dừng ở OCR レビュー / チャンクレビュー: nút đi tới chỗ review và 「すべて承認」
 *  (popup xác nhận → duyệt hết phần còn lại và chạy luôn bước sau). Hiện ở tab パイプライン (card) và tab review
 *  tương ứng (strip): 検査 cho OCR, チャンク cho chunk. */
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Layers, ListChecks, CheckCheck, UserCheck } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useToastError } from "@/components/common";
import { Button, Dialog } from "@/components/ui";
import { api } from "@/lib/api";
import type { Doc } from "@/lib/types";
import { cn } from "@/lib/utils";
import { type ViewerTab, vk } from "./shared";

export type ReviewStage = "ocr" | "chunk" | null;

/** Bước review đang chờ người (chỉ tài liệu duyệt tay; tài liệu tự chạy tự qua các bước này). */
export function reviewStage(doc: Doc | undefined): ReviewStage {
  if (!doc || doc.auto_review) return null;
  if (doc.status === "ocr_review" || doc.status === "ready_for_chunking") return "ocr";
  if (doc.status === "chunk_review") return "chunk";
  return null;
}

export function ReviewGate({
  doc,
  canEdit,
  variant,
  onTab,
}: {
  doc: Doc;
  canEdit: boolean;
  variant: "card" | "strip";
  /** có → nút review của bước chunk mở tab チャンク (không truyền khi đang ở tab đó) */
  onTab?: (t: ViewerTab) => void;
}) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toastError = useToastError();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const stage = reviewStage(doc);
  if (!stage) return null;

  const total = doc.page_to - doc.page_from + 1;
  const pagesDone = doc.stats.approved ?? 0;
  const chunks = doc.stats.chunks ?? 0;
  const chunksDone = doc.stats.chunks_approved ?? 0;
  const left = stage === "ocr" ? total - pagesDone : chunks - chunksDone;
  const allDone = left <= 0;

  const act = async (name: string, ok: string) => {
    setBusy(name);
    try {
      await api.post(`/documents/${doc.id}/actions/${name}`);
      toast.success(ok);
      setConfirm(false);
      qc.invalidateQueries({ queryKey: ["document", doc.id] });
      qc.invalidateQueries({ queryKey: vk.all(doc.id) });
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(null);
    }
  };

  const title = stage === "ocr" ? t("viewer.gate.ocrTitle") : t("viewer.gate.chunkTitle");
  const progress =
    stage === "ocr"
      ? t("viewer.gate.ocrProgress", { n: pagesDone, total })
      : t("viewer.gate.chunkProgress", { n: chunksDone, total: chunks });

  return (
    <>
      <div
        role="status"
        className={cn(
          "flex flex-wrap items-center gap-x-3 gap-y-2 text-sm",
          variant === "card"
            ? "rounded-lg border border-warning/40 bg-warning-soft/70 px-3 py-2.5"
            : "shrink-0 border-b border-warning/30 bg-warning-soft px-4 py-2",
        )}
      >
        {stage === "ocr" ? (
          <UserCheck className="size-4 shrink-0 text-warning" aria-hidden />
        ) : (
          <ListChecks className="size-4 shrink-0 text-warning" aria-hidden />
        )}
        <p className="min-w-0 flex-1 leading-relaxed">
          <span className="font-semibold">{title}</span>
          <span className="ml-2 text-muted-foreground">
            {progress} · {allDone ? t("viewer.gate.allDone") : t("viewer.gate.hint")}
          </span>
        </p>
        {canEdit && (
          <div className="flex flex-wrap items-center gap-2">
            {stage === "ocr" &&
              (allDone ? (
                <Button
                  size="sm"
                  loading={busy === "start_chunking"}
                  onClick={() => act("start_chunking", t("viewer.gate.startedChunking"))}
                >
                  <Layers />
                  {t("detail.startChunking")}
                </Button>
              ) : (
                <Button size="sm" onClick={() => nav(`/documents/${doc.id}/review`)}>
                  <UserCheck />
                  {t("viewer.gate.reviewPages")}
                </Button>
              ))}
            {stage === "chunk" && onTab && (
              <Button size="sm" onClick={() => onTab("chunks")}>
                <ListChecks />
                {t("viewer.gate.reviewChunks")}
              </Button>
            )}
            {!allDone && (
              <Button variant="outline" size="sm" onClick={() => setConfirm(true)}>
                <CheckCheck />
                {t("viewer.gate.approveAll")}
              </Button>
            )}
            {stage === "chunk" && allDone && (
              <Button size="sm" loading={busy === "index"} onClick={() => act("index", t("viewer.gate.startedIndex"))}>
                <Layers />
                {t("detail.startIndex")}
              </Button>
            )}
          </div>
        )}
      </div>

      <Dialog
        open={confirm}
        onOpenChange={setConfirm}
        title={stage === "ocr" ? t("viewer.gate.approveAllOcrTitle") : t("viewer.gate.approveAllChunkTitle")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              loading={busy !== null}
              onClick={() =>
                stage === "ocr"
                  ? act("approve_all_pages", t("viewer.gate.approvedAllOcr"))
                  : act("approve_all_chunks", t("viewer.gate.approvedAllChunk"))
              }
            >
              <CheckCheck />
              {t("viewer.gate.approveAllConfirm")}
            </Button>
          </>
        }
      >
        <div className="flex gap-3 rounded-lg border border-warning/40 bg-warning-soft/60 p-3 text-sm leading-relaxed">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <div className="space-y-1.5">
            <p className="font-medium">
              {stage === "ocr" ? t("viewer.gate.approveAllOcrBody", { n: left }) : t("viewer.gate.approveAllChunkBody", { n: left })}
            </p>
            <p className="text-muted-foreground">
              {stage === "ocr" ? t("viewer.gate.approveAllOcrRisk") : t("viewer.gate.approveAllChunkRisk")}
            </p>
            <p className="text-xs text-muted-foreground">{t("viewer.gate.recorded")}</p>
          </div>
        </div>
      </Dialog>
    </>
  );
}
