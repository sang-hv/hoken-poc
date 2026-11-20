/** Mảnh giao diện dùng ở nhiều tab: cột thumbnail, chọn trang, zoom, hộp thoại nhập prompt. */
import { Minus, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Dialog, Field, Select, Skeleton, Textarea, Tip } from "@/components/ui";
import type { QualityGrade } from "@/lib/v2types";
import { cn } from "@/lib/utils";
import { GRADE_DOT, pageImageUrl } from "./shared";

export interface PageMark {
  grade: QualityGrade;
  weak_open: number;
}

/** Ô chọn trang "ページ 3/18 ▾". */
export function PageJump({
  page,
  total,
  onPage,
  className,
}: {
  page: number;
  total: number;
  onPage: (p: number) => void;
  className?: string;
}) {
  const { t } = useTranslation();
  if (total <= 0) return null;
  return (
    <Select
      aria-label={t("viewer.page.jump")}
      className={cn("h-8 w-auto gap-1 border-transparent bg-transparent px-2 text-xs font-medium shadow-none hover:bg-accent", className)}
      value={String(page)}
      onValueChange={(v) => onPage(Number(v))}
      options={Array.from({ length: total }, (_, i) => ({
        value: String(i + 1),
        label: t("viewer.page.of", { page: i + 1, total }),
      }))}
    />
  );
}

function Thumb({
  docId,
  page,
  active,
  mark,
  onClick,
}: {
  docId: string;
  page: number;
  active: boolean;
  mark?: PageMark;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLButtonElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ block: "nearest" });
  }, [active]);
  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      aria-label={t("viewer.page.alt", { page })}
      aria-current={active ? "page" : undefined}
      className="group flex w-full cursor-pointer flex-col items-center gap-1 rounded-lg p-1.5 outline-none transition hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span
        className={cn(
          "relative block w-full overflow-hidden rounded-md border bg-white transition",
          active ? "border-primary ring-2 ring-primary" : "border-border group-hover:border-muted-foreground/40",
        )}
      >
        {!loaded && !failed && <Skeleton className="aspect-[1/1.414] w-full rounded-none" />}
        {failed && <span className="block aspect-[1/1.414] w-full bg-muted" />}
        {!failed && (
          <img
            src={pageImageUrl(docId, page)}
            alt=""
            loading="lazy"
            onLoad={() => setLoaded(true)}
            onError={() => setFailed(true)}
            className={cn("block w-full", !loaded && "absolute inset-0 opacity-0")}
          />
        )}
        {mark && (
          <span className="absolute right-1 top-1 flex items-center gap-0.5 rounded-full bg-card/95 px-1 py-0.5 shadow-sm">
            <span className={cn("size-2 rounded-full", GRADE_DOT[mark.grade])} aria-hidden />
            {mark.weak_open > 0 && (
              <span className="text-[10px] font-semibold leading-none tabular-nums text-danger">{mark.weak_open}</span>
            )}
          </span>
        )}
      </span>
      <span className={cn("text-[11px] tabular-nums", active ? "font-semibold text-primary" : "text-muted-foreground")}>
        {page}
      </span>
    </button>
  );
}

/** Cột thumbnail bên trái (ẩn ở màn hẹp). */
export function Thumbnails({
  docId,
  total,
  current,
  onSelect,
  marks,
}: {
  docId: string;
  total: number;
  current: number;
  onSelect: (p: number) => void;
  marks?: Record<number, PageMark>;
}) {
  const { t } = useTranslation();
  return (
    <aside
      aria-label={t("viewer.page.thumbs")}
      className="hidden w-32 shrink-0 flex-col border-r border-border bg-sidebar md:flex"
    >
      <div className="flex h-11 shrink-0 items-center justify-center border-b border-border px-1">
        <PageJump page={current} total={total} onPage={onSelect} />
      </div>
      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
        {Array.from({ length: total }, (_, i) => i + 1).map((p) => (
          <Thumb key={p} docId={docId} page={p} active={p === current} mark={marks?.[p]} onClick={() => onSelect(p)} />
        ))}
      </div>
    </aside>
  );
}

export const ZOOM_STEPS = [50, 67, 80, 100, 125, 150, 200];
export function ZoomControl({ zoom, onZoom }: { zoom: number; onZoom: (z: number) => void }) {
  const { t } = useTranslation();
  const i = ZOOM_STEPS.indexOf(zoom);
  return (
    <div className="flex items-center gap-0.5 rounded-lg border border-border bg-card p-0.5 shadow-card">
      <Button
        variant="ghost"
        size="iconSm"
        aria-label={t("viewer.page.zoomOut")}
        disabled={i <= 0}
        onClick={() => onZoom(ZOOM_STEPS[Math.max(0, i - 1)])}
      >
        <Minus />
      </Button>
      <Tip content={t("viewer.page.zoomReset")}>
        <button
          type="button"
          onClick={() => onZoom(100)}
          aria-label={t("viewer.page.zoomReset")}
          className="h-7 min-w-12 cursor-pointer rounded-md px-1 text-xs font-medium tabular-nums hover:bg-accent"
        >
          {zoom}%
        </button>
      </Tip>
      <Button
        variant="ghost"
        size="iconSm"
        aria-label={t("viewer.page.zoomIn")}
        disabled={i >= ZOOM_STEPS.length - 1}
        onClick={() => onZoom(ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, i + 1)])}
      >
        <Plus />
      </Button>
    </div>
  );
}

/** Hộp thoại "chạy lại bằng AI" với prompt tuỳ chọn. */
export function PromptDialog({
  open,
  onOpenChange,
  title,
  description,
  onRun,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  onRun: (prompt: string) => Promise<unknown>;
}) {
  const { t } = useTranslation();
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) setPrompt("");
  }, [open]);
  const run = async () => {
    setBusy(true);
    try {
      await onRun(prompt.trim());
      onOpenChange(false);
    } catch {
      /* onRun tự hiện toast lỗi */
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("viewer.detail.cancel")}
          </Button>
          <Button loading={busy} onClick={run}>
            {t("viewer.reread.run")}
          </Button>
        </>
      }
    >
      <Field label={t("viewer.reread.prompt")}>
        <Textarea
          rows={3}
          value={prompt}
          placeholder={t("viewer.reread.placeholder")}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "Enter") run();
          }}
        />
      </Field>
    </Dialog>
  );
}
