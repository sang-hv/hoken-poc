import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button, Dialog } from "./ui";

export function PageHeader({
  title,
  subtitle,
  actions,
  breadcrumb,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  breadcrumb?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {breadcrumb && <div className="mb-1.5 text-sm text-muted-foreground">{breadcrumb}</div>}
        <h1 className="break-words text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function useErrorText() {
  const { t } = useTranslation();
  return (e: unknown) => {
    if (e instanceof ApiError) {
      const msg = t(`errors.${e.code}`, { ...e.detail, defaultValue: "" });
      if (msg) return msg;
      if (e.detail.message) return String(e.detail.message);
      return `${t("errors.generic")} (${e.code})`;
    }
    return t("errors.generic");
  };
}

export function useToastError() {
  const text = useErrorText();
  return (e: unknown) => toast.error(text(e));
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  danger,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  confirmLabel?: React.ReactNode;
  onConfirm: () => Promise<unknown> | void;
  danger?: boolean;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button
            variant={danger ? "danger" : "default"}
            loading={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
                onOpenChange(false);
              } finally {
                setBusy(false);
              }
            }}
          >
            {confirmLabel ?? t("common.confirm")}
          </Button>
        </>
      }
    />
  );
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cn("prose-md", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

export function StatCard({
  label,
  value,
  icon,
  tone = "primary",
  hint,
  onClick,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  icon: React.ReactNode;
  tone?: "primary" | "warning" | "danger" | "info" | "success" | "violet";
  hint?: React.ReactNode;
  onClick?: () => void;
}) {
  const bg: Record<string, string> = {
    primary: "bg-primary-soft text-primary",
    warning: "bg-warning-soft text-warning",
    danger: "bg-danger-soft text-danger",
    info: "bg-info-soft text-info",
    success: "bg-success-soft text-success",
    violet: "bg-violet-soft text-violet",
  };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      className="group flex items-center gap-4 rounded-xl border border-border bg-card p-4 text-left shadow-card transition enabled:hover:-translate-y-0.5 enabled:hover:shadow-md disabled:cursor-default"
    >
      <div className={cn("rounded-xl p-2.5 [&_svg]:size-5", bg[tone])}>{icon}</div>
      <div className="min-w-0">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className="text-2xl font-semibold tabular-nums">{value}</p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
    </button>
  );
}

/** Thanh phân trang: "1–20 / 57" + nút trước/sau. Ẩn khi chỉ có một trang. */
export function Pagination({
  page,
  size,
  total,
  onPage,
  className,
}: {
  page: number;
  size: number;
  total: number;
  onPage: (p: number) => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const pages = Math.max(1, Math.ceil(total / size));
  if (total <= size) return null;
  const from = (page - 1) * size + 1;
  const to = Math.min(total, page * size);
  return (
    <div className={cn("flex items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-xs", className)}>
      <span className="tabular-nums text-muted-foreground">{t("common.range", { from, to, total })}</span>
      <span className="flex items-center gap-1">
        <Button variant="ghost" size="iconSm" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label={t("common.prev")}>
          <ChevronLeft />
        </Button>
        <span className="min-w-14 text-center tabular-nums">
          {page} / {pages}
        </span>
        <Button
          variant="ghost"
          size="iconSm"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
          aria-label={t("common.next")}
        >
          <ChevronRight />
        </Button>
      </span>
    </div>
  );
}
