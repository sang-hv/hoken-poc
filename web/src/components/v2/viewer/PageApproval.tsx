/** Duyệt trang ngay trong tab 検査 (tài liệu duyệt tay, bước OCR レビュー): trạng thái trang + 「このページを承認」
 *  (Ctrl/⌘+Enter) → tự sang trang chưa duyệt kế tiếp; trang đã duyệt có 「承認を取り消す」. Thay màn review cũ. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Undo2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useToastError } from "@/components/common";
import { Badge, Button, Tip } from "@/components/ui";
import { api } from "@/lib/api";
import type { Page } from "@/lib/types";
import { reviewStage } from "./ReviewGate";
import { isTypingTarget, useDocMeta, vk } from "./shared";

export function PageApproval({
  docId,
  page,
  onPage,
  canEdit,
}: {
  docId: string;
  page: number;
  onPage: (p: number) => void;
  canEdit: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();
  const doc = useDocMeta(docId).data;
  const active = reviewStage(doc) === "ocr";
  const pages = useQuery({
    queryKey: vk.pages(docId),
    queryFn: () => api.get<Page[]>(`/documents/${docId}/pages`),
    enabled: active,
  });
  const [busy, setBusy] = useState(false);
  const cur = pages.data?.find((p) => p.page === page);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: vk.pages(docId) });
    qc.invalidateQueries({ queryKey: ["document", docId] });
  };
  const approve = useCallback(async () => {
    if (!cur || cur.status !== "review" || busy) return;
    setBusy(true);
    try {
      await api.post(`/documents/${docId}/pages/${page}/submit`, {});
      refresh();
      const rest = (pages.data ?? []).filter((p) => p.status === "review" && p.page !== page).map((p) => p.page);
      const next = rest.find((p) => p > page) ?? rest[0];
      if (next) {
        toast.success(t("viewer.approval.approvedNext", { page, next }));
        onPage(next);
      } else toast.success(t("viewer.approval.allApproved"));
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cur, busy, docId, page, pages.data, onPage]);

  const reopen = async () => {
    setBusy(true);
    try {
      await api.post(`/documents/${docId}/pages/${page}/reopen`);
      refresh();
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(false);
    }
  };

  // Ctrl/⌘+Enter = 承認 (không khi đang gõ trong ô sửa phần tử)
  const approveRef = useRef(approve);
  approveRef.current = approve;
  useEffect(() => {
    if (!active || !canEdit) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Enter" || !(e.ctrlKey || e.metaKey) || isTypingTarget(e.target)) return;
      e.preventDefault();
      approveRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, canEdit]);

  if (!active || !cur) return null;
  if (cur.status === "approved")
    return (
      <span className="flex items-center gap-2">
        <Tip content={cur.reviewed_by ? t("viewer.approval.by", { by: cur.reviewed_by }) : ""}>
          <Badge tone="success">
            <Check />
            {t("viewer.approval.approved")}
          </Badge>
        </Tip>
        {canEdit && (
          <Button variant="ghost" size="sm" loading={busy} onClick={reopen}>
            <Undo2 />
            {t("viewer.approval.reopen")}
          </Button>
        )}
      </span>
    );
  if (cur.status !== "review") return null;
  return (
    <span className="flex items-center gap-2">
      <Badge tone="warning">{t("viewer.approval.needsReview")}</Badge>
      {canEdit && (
        <Tip content={t("viewer.approval.shortcut")}>
          <Button size="sm" loading={busy} onClick={approve}>
            <Check />
            {t("viewer.approval.approve")}
          </Button>
        </Tip>
      )}
    </span>
  );
}
