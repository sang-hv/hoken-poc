import { useQuery } from "@tanstack/react-query";
import { RotateCcw, Settings } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Badge, Button, Dialog, Skeleton, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { QueryError, vk } from "./shared";

const MAX = 4000; // = REREAD_MAX phía backend

/** Hộp thoại 「弱点をAIで修正」: hiện hướng dẫn mặc định (settings `quality.reread_prompt`), cho sửa riêng lần chạy này.
 *  Bản đã sửa được giữ lại trong lúc màn còn mở để chạy lại không phải gõ lại. */
export function FixWeakDialog({
  docId,
  open,
  onOpenChange,
  onRun,
  weakOpen,
}: {
  docId: string;
  /** số điểm yếu đang biết (hiện trước khi tải xong) */
  weakOpen: number;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  /** prompt rỗng = dùng mặc định trong settings */
  onRun: (prompt: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const info = useQuery({
    queryKey: [...vk.all(docId), "fix-weak"],
    queryFn: () => api.get<{ prompt: string; weak: number }>(`/documents/${docId}/fix-weak`),
    enabled: open,
    staleTime: 0,
  });
  const [custom, setCustom] = useState<string | null>(null); // null = đang dùng mặc định
  const [busy, setBusy] = useState(false);
  const def = info.data?.prompt ?? "";
  const text = custom ?? def;
  const isDefault = custom === null || custom === def;
  const n = info.data?.weak ?? weakOpen;
  const tooLong = text.length > MAX;

  const run = async () => {
    setBusy(true);
    try {
      await onRun(isDefault ? "" : text.trim());
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("viewer.quality.fixTitle")}
      description={t("viewer.quality.fixDesc", { n })}
      className="max-w-2xl"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button loading={busy} disabled={!info.data || n === 0 || !text.trim() || tooLong} onClick={run}>
            {t("viewer.quality.fixRun")}
          </Button>
        </>
      }
    >
      {info.isError ? (
        <QueryError error={info.error} onRetry={() => info.refetch()} />
      ) : !info.data ? (
        <Skeleton className="h-48" />
      ) : (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label htmlFor="fix-weak-prompt" className="text-sm font-medium">
              {t("viewer.quality.promptLabel")}
            </label>
            <span className="flex items-center gap-2">
              {isDefault ? (
                <Badge tone="neutral">{t("viewer.quality.promptDefault")}</Badge>
              ) : (
                <>
                  <Badge tone="warning">{t("viewer.quality.promptCustom")}</Badge>
                  <Button variant="ghost" size="sm" onClick={() => setCustom(null)}>
                    <RotateCcw />
                    {t("viewer.quality.promptReset")}
                  </Button>
                </>
              )}
            </span>
          </div>
          <Textarea
            id="fix-weak-prompt"
            rows={9}
            className={cn("font-mono text-xs leading-relaxed", tooLong && "border-danger")}
            value={text}
            onChange={(e) => setCustom(e.target.value)}
          />
          <div className="flex flex-wrap items-start justify-between gap-2 text-xs text-muted-foreground">
            <p className="min-w-0 flex-1 leading-relaxed">{t("viewer.quality.promptHint")}</p>
            <span className={cn("tabular-nums", tooLong && "text-danger")}>
              {text.length}/{MAX}
            </span>
          </div>
          {can("admin") && (
            <Link
              to="/settings?tab=pipeline"
              className="inline-flex w-fit items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              <Settings className="size-3.5" aria-hidden />
              {t("viewer.quality.promptSettings")}
            </Link>
          )}
        </div>
      )}
    </Dialog>
  );
}
