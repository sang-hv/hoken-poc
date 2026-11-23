/** Bước review chờ người (review.mode warn khi có cảnh báo, hoặc manual):
 *  - `ReviewGate`: dải một dòng dưới thanh trên (tab パイプライン + tab review tương ứng: 検査 cho OCR, チャンク cho
 *    chunk) — đây là nơi chính báo trạng thái chờ review.
 *  - `ReviewPrompt`: popup CHỈ khi pipeline vừa dừng ở bước review trong lúc người dùng đang xem (không bật mỗi lần
 *    mở / tải lại màn — modal lúc tải trang chặn người dùng mà banner đã nói cùng nội dung).
 *  「すべて承認」 luôn qua bước xác nhận (ghi audit, người duyệt = người bấm) rồi chạy luôn bước sau. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCheck, ListChecks, UserCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useToastError } from "@/components/common";
import { Button, Checkbox, Dialog } from "@/components/ui";
import { api } from "@/lib/api";
import type { Doc } from "@/lib/types";
import type { DocQuality } from "@/lib/v2types";
import { type ViewerTab, vk } from "./shared";

export type ReviewMode = "auto" | "warn" | "manual";
export type ReviewStage = "ocr" | "chunk" | null;

/** review.mode lúc upload (tài liệu cũ chưa có → suy ra từ auto_review). */
export function reviewMode(doc: Doc | undefined): ReviewMode {
  if (!doc) return "auto";
  return (doc.review_mode as ReviewMode) || (doc.auto_review ? "auto" : "manual");
}

/** Bước review đang chờ người: manual → mọi lần tới bước review; warn → chỉ khi pipeline dừng vì có cảnh báo. */
export function reviewStage(doc: Doc | undefined): ReviewStage {
  const mode = reviewMode(doc);
  if (!doc || mode === "auto") return null;
  const ocr = doc.status === "ocr_review" || doc.status === "ready_for_chunking";
  const chunk = doc.status === "chunk_review";
  if (mode === "manual") return ocr ? "ocr" : chunk ? "chunk" : null;
  if (ocr && doc.review_hold === "ocr") return "ocr";
  if (chunk && doc.review_hold === "chunk") return "chunk";
  return null;
}

function counts(doc: Doc, stage: Exclude<ReviewStage, null>) {
  const total = doc.page_to - doc.page_from + 1;
  const pagesDone = doc.stats.approved ?? 0;
  const chunks = doc.stats.chunks ?? 0;
  const chunksDone = doc.stats.chunks_approved ?? 0;
  return stage === "ocr"
    ? { done: pagesDone, total, left: total - pagesDone }
    : { done: chunksDone, total: chunks, left: chunks - chunksDone };
}

function useApproveAll(doc: Doc, onDone: () => void) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();
  const [busy, setBusy] = useState<string | null>(null);
  const act = async (name: string, ok: string) => {
    setBusy(name);
    try {
      // すべて承認 phải gửi confirm: true (backend từ chối nếu thiếu — chống gọi nhầm)
      await api.post(`/documents/${doc.id}/actions/${name}`, name.startsWith("approve_all") ? { confirm: true } : undefined);
      toast.success(ok);
      onDone();
      qc.invalidateQueries({ queryKey: ["document", doc.id] });
      qc.invalidateQueries({ queryKey: vk.all(doc.id) });
      qc.invalidateQueries({ queryKey: vk.pages(doc.id) });
      qc.invalidateQueries({ queryKey: ["chunks-list", doc.id] });
      qc.invalidateQueries({ queryKey: ["chunk", doc.id] });
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(null);
    }
  };
  const approveAll = (stage: Exclude<ReviewStage, null>) =>
    stage === "ocr"
      ? act("approve_all_pages", t("viewer.gate.approvedAllOcr"))
      : act("approve_all_chunks", t("viewer.gate.approvedAllChunk"));
  return { busy, act, approveAll };
}

/** Popup review. Bước 1 (`onReview` có): số cảnh báo + 「レビューする」 (nút chính) / 「すべて承認…」. Bước 2 (xác nhận
 *  lần nữa — duyệt mà không review là nguy hiểm): số trang/chunk chưa review + cảnh báo, phải tích 「理解しました」
 *  mới bấm được 「すべて承認する」. Không truyền `onReview` (banner) → vào thẳng bước 2. */
function ReviewDialog({
  doc,
  stage,
  open,
  onOpenChange,
  onReview,
}: {
  doc: Doc;
  stage: Exclude<ReviewStage, null>;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onReview?: () => void;
}) {
  const { t } = useTranslation();
  const { busy, approveAll } = useApproveAll(doc, () => onOpenChange(false));
  const quality = useQuery({
    queryKey: vk.quality(doc.id),
    queryFn: () => api.get<DocQuality>(`/documents/${doc.id}/quality`),
    enabled: open && stage === "ocr",
  });
  const [step, setStep] = useState<"choose" | "confirm">(onReview ? "choose" : "confirm");
  const [ack, setAck] = useState(false);
  useEffect(() => {
    if (open) {
      setStep(onReview ? "choose" : "confirm");
      setAck(false);
    }
  }, [open, onReview]);
  const c = counts(doc, stage);
  const warnings = stage === "ocr" ? quality.data?.weak_open : doc.stats.chunks_flagged;
  const held = reviewMode(doc) === "warn";
  const ocr = stage === "ocr";

  if (step === "choose")
    return (
      <Dialog
        open={open}
        onOpenChange={onOpenChange}
        className="max-w-xl"
        title={ocr ? t("viewer.gate.promptOcrTitle") : t("viewer.gate.promptChunkTitle")}
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              {t("viewer.gate.later")}
            </Button>
            <Button
              data-autofocus
              onClick={() => {
                onOpenChange(false);
                onReview?.();
              }}
            >
              {ocr ? <UserCheck /> : <ListChecks />}
              {ocr ? t("viewer.gate.reviewPages") : t("viewer.gate.reviewChunks")}
            </Button>
            <Button variant="outline" disabled={c.left <= 0} onClick={() => setStep("confirm")}>
              <CheckCheck />
              {t("viewer.gate.approveAll")}
            </Button>
          </>
        }
      >
        <div className="space-y-2 text-sm leading-relaxed">
          <p>
            {held
              ? ocr
                ? t("viewer.gate.heldOcr", { n: warnings ?? "…" })
                : t("viewer.gate.heldChunk", { n: warnings ?? "…" })
              : ocr
                ? t("viewer.gate.manualOcr")
                : t("viewer.gate.manualChunk")}
          </p>
          <p className="text-muted-foreground">
            {ocr
              ? t("viewer.gate.ocrProgress", { n: c.done, total: c.total })
              : t("viewer.gate.chunkProgress", { n: c.done, total: c.total })}
          </p>
        </div>
      </Dialog>
    );

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      className="max-w-xl"
      title={ocr ? t("viewer.gate.approveAllOcrTitle") : t("viewer.gate.approveAllChunkTitle")}
      footer={
        <>
          <Button variant="ghost" onClick={() => (onReview ? setStep("choose") : onOpenChange(false))}>
            {onReview ? t("viewer.gate.back") : t("common.cancel")}
          </Button>
          <Button variant="danger" loading={busy !== null} disabled={!ack || c.left <= 0} onClick={() => approveAll(stage)}>
            <CheckCheck />
            {t("viewer.gate.approveAllConfirm")}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm leading-relaxed">
        <p className="font-medium">
          {ocr ? t("viewer.gate.approveAllOcrBody", { n: c.left }) : t("viewer.gate.approveAllChunkBody", { n: c.left })}
        </p>
        {warnings !== undefined && warnings > 0 && (
          <p className="flex items-start gap-2 text-danger">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {ocr ? t("viewer.gate.warnOcr", { n: warnings }) : t("viewer.gate.warnChunk", { n: warnings })}
          </p>
        )}
        <p className="text-muted-foreground">
          {ocr ? t("viewer.gate.approveAllOcrRisk") : t("viewer.gate.approveAllChunkRisk")} {t("viewer.gate.recorded")}
        </p>
        <label className="flex cursor-pointer items-start gap-2.5 border-t border-border pt-3">
          <Checkbox data-autofocus checked={ack} onCheckedChange={(v) => setAck(v === true)} className="mt-0.5" />
          <span>{ocr ? t("viewer.gate.ackOcr") : t("viewer.gate.ackChunk")}</span>
        </label>
      </div>
    </Dialog>
  );
}

/** Popup khi pipeline vừa dừng ở bước review trong lúc đang xem tab パイプライン (trạng thái đổi từ "không chờ" sang
 *  "chờ" trong phiên này). Mở / tải lại màn khi tài liệu đã đang chờ → không popup, banner ReviewGate đã đủ. */
export function ReviewPrompt({
  doc,
  canEdit,
  onTab,
  onPipeline,
}: {
  doc: Doc | undefined;
  canEdit: boolean;
  onTab: (t: ViewerTab) => void;
  /** đang ở tab パイプライン */
  onPipeline: boolean;
}) {
  const nav = useNavigate();
  const stage = reviewStage(doc);
  const [open, setOpen] = useState(false);
  // Đã duyệt hết (chỉ còn bấm bước sau — banner có nút) → không cần popup
  const pending = !!doc && !!stage && counts(doc, stage).left > 0;
  // Bước chờ ở lần render trước; `undefined` = chưa tải tài liệu (lần tải đầu không tính là "vừa dừng")
  const prev = useRef<ReviewStage | undefined>(undefined);
  useEffect(() => {
    if (!doc) return;
    const before = prev.current;
    prev.current = stage;
    if (before !== undefined && before !== stage && stage && pending && canEdit && onPipeline) setOpen(true);
    if (!stage) setOpen(false);
  }, [doc, stage, pending, canEdit, onPipeline]);
  // Đổi tài liệu → coi như tải lần đầu
  useEffect(() => {
    prev.current = undefined;
  }, [doc?.id]);
  if (!doc || !stage) return null;
  return (
    <ReviewDialog
      doc={doc}
      stage={stage}
      open={open}
      onOpenChange={setOpen}
      onReview={() => (stage === "ocr" ? nav(`/documents/${doc.id}/review`) : onTab("chunks"))}
    />
  );
}

export function ReviewGate({
  doc,
  canEdit,
  onTab,
}: {
  doc: Doc;
  canEdit: boolean;
  /** có → nút review của bước chunk mở tab チャンク (không truyền khi đang ở tab đó) */
  onTab?: (t: ViewerTab) => void;
}) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const [confirm, setConfirm] = useState(false);
  const stage = reviewStage(doc);
  const { busy, act } = useApproveAll(doc, () => setConfirm(false));
  if (!stage) return null;

  const c = counts(doc, stage);
  const allDone = c.left <= 0;
  const held = reviewMode(doc) === "warn";
  const title = stage === "ocr" ? t("viewer.gate.ocrTitle") : t("viewer.gate.chunkTitle");
  const progress =
    stage === "ocr"
      ? t("viewer.gate.ocrProgress", { n: c.done, total: c.total })
      : t("viewer.gate.chunkProgress", { n: c.done, total: c.total });

  return (
    <>
      <div
        role="status"
        className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-warning/30 bg-warning-soft px-4 py-1.5 text-sm"
      >
        <span className="size-1.5 shrink-0 rounded-full bg-warning" aria-hidden />
        <p className="min-w-0 flex-1 leading-relaxed">
          <span className="font-medium">{title}</span>
          <span className="ml-2 text-muted-foreground">
            {held && <>{t("viewer.gate.heldShort")} · </>}
            {progress}
            {allDone && <> · {t("viewer.gate.allDone")}</>}
          </span>
        </p>
        {canEdit && (
          <div className="flex flex-wrap items-center gap-1.5">
            {!allDone && (
              <Button variant="ghost" size="sm" className="h-7" onClick={() => setConfirm(true)}>
                {t("viewer.gate.approveAll")}
              </Button>
            )}
            {stage === "ocr" &&
              (allDone ? (
                <Button
                  size="sm"
                  className="h-7"
                  loading={busy === "start_chunking"}
                  onClick={() => act("start_chunking", t("viewer.gate.startedChunking"))}
                >
                  {t("detail.startChunking")}
                </Button>
              ) : (
                <Button size="sm" className="h-7" onClick={() => nav(`/documents/${doc.id}/review`)}>
                  {t("viewer.gate.reviewPages")}
                </Button>
              ))}
            {stage === "chunk" && onTab && !allDone && (
              <Button size="sm" className="h-7" onClick={() => onTab("chunks")}>
                {t("viewer.gate.reviewChunks")}
              </Button>
            )}
            {stage === "chunk" && allDone && (
              <Button size="sm" className="h-7" loading={busy === "index"} onClick={() => act("index", t("viewer.gate.startedIndex"))}>
                {t("detail.startIndex")}
              </Button>
            )}
          </div>
        )}
      </div>
      <ReviewDialog doc={doc} stage={stage} open={confirm} onOpenChange={setConfirm} />
    </>
  );
}
