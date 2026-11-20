import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CircleAlert,
  ExternalLink,
  FileText,
  FileUp,
  Image as ImageIcon,
  Loader2,
  MoreHorizontal,
  Plus,
  Trash2,
} from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ConfirmDialog, useToastError } from "@/components/common";
import {
  Badge,
  Button,
  Checkbox,
  Dropdown,
  DropdownContent,
  DropdownItem,
  DropdownTrigger,
  Progress,
  Tip,
} from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { NotebookDetail, NotebookSource } from "@/lib/v2types";
import { Column, GradeChip, isSettled, nbKeys } from "./shared";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg";
const OK_TYPES = ["application/pdf", "image/png", "image/jpeg"];
const okFile = (f: File) => OK_TYPES.includes(f.type) || /\.(pdf|png|jpe?g)$/i.test(f.name);

interface PendingUpload {
  id: number;
  name: string;
  file_type: "pdf" | "image";
}

function FileIcon({ type }: { type: "pdf" | "image" }) {
  return type === "pdf" ? (
    <FileText className="size-4 shrink-0 text-danger" aria-hidden />
  ) : (
    <ImageIcon className="size-4 shrink-0 text-info" aria-hidden />
  );
}

/** Dòng trạng thái của một nguồn: bước đang chạy + tiến độ / hạng chất lượng + 要確認 / lỗi. */
function SourceState({ s }: { s: NotebookSource }) {
  const { t } = useTranslation();
  if (s.stage === "failed") {
    return (
      <div className="flex items-start gap-1.5 text-xs text-danger" title={s.error || undefined}>
        <CircleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
        <span>
          <span className="font-medium">{t("nb.sources.failed")}</span>
          <span className="block text-muted-foreground">{t("nb.sources.failedHint")}</span>
        </span>
      </div>
    );
  }
  if (s.stage !== "done") {
    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span className="flex min-w-0 items-center gap-1.5">
            <Loader2 className="size-3 shrink-0 animate-spin text-primary" aria-hidden />
            <span className="truncate">{t(`nb.stage.${s.stage}`)}</span>
          </span>
          <span className="tabular-nums">{Math.round(s.progress)}%</span>
        </div>
        <Progress value={s.progress} className="h-1" />
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {s.quality && <GradeChip grade={s.quality.grade} score={s.quality.score} />}
      {s.weak_open > 0 && (
        <Tip content={t("nb.sources.weakHint", { n: s.weak_open })}>
          <Badge tone="warning" tabIndex={0}>
            <AlertTriangle />
            {t("nb.sources.weak", { n: s.weak_open })}
          </Badge>
        </Tip>
      )}
      {s.pages > 0 && <span className="text-[11px] text-muted-foreground">{t("nb.sources.pages", { count: s.pages })}</span>}
    </div>
  );
}

function SourceRow({
  nbId,
  s,
  canEdit,
  onToggle,
  onDelete,
}: {
  nbId: string;
  s: NotebookSource;
  canEdit: boolean;
  onToggle: (s: NotebookSource, enabled: boolean) => void;
  onDelete: (s: NotebookSource) => void;
}) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const href = `/notebooks/${nbId}/sources/${s.doc_id}`;
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  return (
    <li
      onClick={() => nav(href)}
      className={cn(
        "group flex cursor-pointer gap-2.5 border-b border-border px-3 py-2.5 transition last:border-b-0 hover:bg-accent/60",
        s.stage === "failed" && "bg-danger-soft/40",
      )}
    >
      <div className="pt-0.5" onClick={stop}>
        <Checkbox
          checked={s.enabled}
          disabled={!canEdit}
          onCheckedChange={(v) => onToggle(s, v === true)}
          aria-label={t("nb.sources.use", { name: s.name })}
        />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex min-w-0 items-center gap-1.5">
          <FileIcon type={s.file_type} />
          <Link
            to={href}
            onClick={stop}
            title={s.name}
            className={cn("min-w-0 flex-1 truncate text-sm font-medium hover:text-primary", !s.enabled && "text-muted-foreground")}
          >
            {s.name}
          </Link>
          <Badge tone="neutral" className="shrink-0 px-1.5 text-[10px]">
            {t("nb.sources.modeFull")}
          </Badge>
        </div>
        <SourceState s={s} />
      </div>
      <div onClick={stop} className="-mr-1">
        <Dropdown>
          <DropdownTrigger asChild>
            <Button
              variant="ghost"
              size="iconSm"
              aria-label={t("nb.sources.menu")}
              className="text-muted-foreground opacity-70 group-hover:opacity-100"
            >
              <MoreHorizontal />
            </Button>
          </DropdownTrigger>
          <DropdownContent>
            <DropdownItem onSelect={() => nav(href)}>
              <ExternalLink />
              {t("nb.sources.open")}
            </DropdownItem>
            {canEdit && (
              <DropdownItem onSelect={() => onDelete(s)} className="text-danger [&_svg]:text-danger">
                <Trash2 />
                {t("nb.sources.delete")}
              </DropdownItem>
            )}
          </DropdownContent>
        </Dropdown>
      </div>
    </li>
  );
}

export function SourcesColumn({ nb, canEdit, className }: { nb: NotebookDetail; canEdit: boolean; className?: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();
  const input = useRef<HTMLInputElement>(null);
  const nextId = useRef(1);
  const [drag, setDrag] = useState(false);
  const [pending, setPending] = useState<PendingUpload[]>([]);
  const [toDelete, setToDelete] = useState<NotebookSource | null>(null);
  const key = nbKeys.detail(nb.id);

  const upload = (files: FileList | File[] | null) => {
    if (!files) return;
    for (const f of Array.from(files)) {
      if (!okFile(f)) {
        toast.error(t("nb.sources.unsupported", { name: f.name }));
        continue;
      }
      const id = nextId.current++;
      const file_type = /pdf/i.test(f.type) || /\.pdf$/i.test(f.name) ? "pdf" : "image";
      setPending((p) => [...p, { id, name: f.name, file_type }]);
      const fd = new FormData();
      fd.append("file", f);
      api
        .post<NotebookSource>(`/notebooks/${nb.id}/sources`, fd)
        .then((src) => {
          // Chèn ngay nguồn mới để thanh tiến độ hiện liền, rồi để poll cập nhật
          qc.setQueryData<NotebookDetail>(key, (d) =>
            d && !d.sources.some((x) => x.doc_id === src.doc_id)
              ? { ...d, sources: [...d.sources, src], source_count: d.source_count + 1 }
              : d,
          );
          qc.invalidateQueries({ queryKey: key });
          qc.invalidateQueries({ queryKey: nbKeys.list });
          toast.success(t("nb.sources.uploaded", { name: f.name }));
        })
        .catch(toastError)
        .finally(() => setPending((p) => p.filter((x) => x.id !== id)));
    }
  };

  const toggle = async (s: NotebookSource, enabled: boolean) => {
    const set = (v: boolean) =>
      qc.setQueryData<NotebookDetail>(key, (d) =>
        d ? { ...d, sources: d.sources.map((x) => (x.doc_id === s.doc_id ? { ...x, enabled: v } : x)) } : d,
      );
    set(enabled);
    try {
      await api.patch<NotebookSource>(`/notebooks/${nb.id}/sources/${s.doc_id}`, { enabled });
    } catch (e) {
      set(!enabled);
      toastError(e);
    }
  };

  const running = nb.sources.filter((s) => !isSettled(s)).length;

  return (
    <Column
      title={t("nb.sources.title")}
      count={nb.sources.length}
      className={className}
      actions={
        canEdit && (
          <Button variant="soft" size="sm" onClick={() => input.current?.click()}>
            <Plus />
            {t("nb.sources.add")}
          </Button>
        )
      }
      footer={
        canEdit ? (
          <div className="shrink-0 border-t border-border p-3">
            <button
              type="button"
              onClick={() => input.current?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDrag(false);
                upload(e.dataTransfer.files);
              }}
              className={cn(
                "flex w-full flex-col items-center gap-1 rounded-lg border-2 border-dashed px-3 py-4 text-center text-xs transition",
                drag ? "border-primary bg-primary-soft text-primary" : "border-border text-muted-foreground hover:border-primary/60 hover:bg-accent",
              )}
            >
              <FileUp className="size-5 text-primary" aria-hidden />
              <span className="font-medium">{drag ? t("nb.sources.dropActive") : t("nb.sources.drop")}</span>
              <span className="text-[11px]">{t("nb.sources.dropTypes")}</span>
            </button>
            <input
              ref={input}
              type="file"
              accept={ACCEPT}
              multiple
              hidden
              onChange={(e) => {
                upload(e.target.files);
                e.target.value = "";
              }}
            />
          </div>
        ) : (
          <p className="shrink-0 border-t border-border px-3 py-2 text-[11px] text-muted-foreground">{t("nb.sources.readOnly")}</p>
        )
      }
    >
      {nb.sources.length === 0 && pending.length === 0 ? (
        <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
          <div className="rounded-xl bg-muted p-2.5 text-muted-foreground">
            <FileText className="size-5" />
          </div>
          <p className="text-sm font-medium">{t("nb.sources.emptyTitle")}</p>
          <p className="text-xs text-muted-foreground">{t("nb.sources.emptyHint")}</p>
        </div>
      ) : (
        <ul aria-live="polite" aria-busy={running > 0 || pending.length > 0}>
          {nb.sources.map((s) => (
            <SourceRow key={s.doc_id} nbId={nb.id} s={s} canEdit={canEdit} onToggle={toggle} onDelete={setToDelete} />
          ))}
          {pending.map((p) => (
            <li key={`up-${p.id}`} className="flex gap-2.5 border-b border-border px-3 py-2.5 last:border-b-0">
              <div className="size-4" />
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <div className="flex min-w-0 items-center gap-1.5">
                  <FileIcon type={p.file_type} />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-muted-foreground" title={p.name}>
                    {p.name}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="size-3 animate-spin text-primary" aria-hidden />
                  {t("nb.stage.upload")}
                </div>
                <Progress value={5} className="h-1" />
              </div>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={!!toDelete}
        onOpenChange={(o) => !o && setToDelete(null)}
        title={t("nb.sources.deleteTitle")}
        description={toDelete ? t("nb.sources.deleteConfirm", { name: toDelete.name }) : ""}
        danger
        confirmLabel={t("nb.sources.delete")}
        onConfirm={async () => {
          const s = toDelete!;
          try {
            await api.del(`/notebooks/${nb.id}/sources/${s.doc_id}`);
            qc.setQueryData<NotebookDetail>(key, (d) =>
              d ? { ...d, sources: d.sources.filter((x) => x.doc_id !== s.doc_id), source_count: Math.max(0, d.source_count - 1) } : d,
            );
            qc.invalidateQueries({ queryKey: key });
            qc.invalidateQueries({ queryKey: nbKeys.list });
            toast.success(t("nb.sources.deleted"));
          } catch (e) {
            toastError(e);
          }
        }}
      />
    </Column>
  );
}
