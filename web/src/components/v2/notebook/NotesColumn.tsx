import { useQueryClient } from "@tanstack/react-query";
import { Info, Plus, StickyNote, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ConfirmDialog, useToastError } from "@/components/common";
import { Button, Dialog, Field, Input, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtRelative } from "@/lib/utils";
import type { Note, NotebookDetail } from "@/lib/v2types";
import { Column, nbKeys } from "./shared";

/** Ghi chú đang mở: `"new"` = tạo mới, `Note` = sửa, `null` = đóng. */
export type NoteTarget = Note | "new" | null;

export function NoteDialog({
  nbId,
  target,
  canEdit,
  onClose,
}: {
  nbId: string;
  target: NoteTarget;
  canEdit: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const note = target && target !== "new" ? target : null;
  const key = nbKeys.detail(nbId);

  useEffect(() => {
    if (!target) return;
    setTitle(note?.title ?? "");
    setText(note?.text ?? "");
  }, [target]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      const saved = note
        ? await api.patch<Note>(`/notebooks/${nbId}/notes/${note.id}`, { title: title.trim(), text })
        : await api.post<Note>(`/notebooks/${nbId}/notes`, { title: title.trim(), text });
      qc.setQueryData<NotebookDetail>(key, (d) => {
        if (!d) return d;
        const exists = d.notes.some((n) => n.id === saved.id);
        return exists
          ? { ...d, notes: d.notes.map((n) => (n.id === saved.id ? saved : n)) }
          : { ...d, notes: [saved, ...d.notes], note_count: d.note_count + 1 };
      });
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: nbKeys.list });
      toast.success(t("nb.notes.saved"));
      onClose();
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Dialog
        open={!!target}
        onOpenChange={(o) => !o && onClose()}
        title={note ? t("nb.notes.editTitle") : t("nb.notes.newTitle")}
        description={t("nb.notes.hint")}
        className="max-w-2xl"
        footer={
          <>
            {note && canEdit && (
              <Button variant="ghost" className="mr-auto text-danger" onClick={() => setConfirm(true)}>
                <Trash2 />
                {t("nb.notes.delete")}
              </Button>
            )}
            <Button variant="ghost" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            {canEdit && (
              <Button onClick={save} loading={busy} disabled={!text.trim()}>
                {t("common.save")}
              </Button>
            )}
          </>
        }
      >
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <Field label={t("nb.notes.titleLabel")}>
            <Input
              value={title}
              maxLength={200}
              readOnly={!canEdit}
              placeholder={t("nb.notes.titlePlaceholder")}
              onChange={(e) => setTitle(e.target.value)}
            />
          </Field>
          <Field label={t("nb.notes.textLabel")}>
            <Textarea
              rows={12}
              value={text}
              readOnly={!canEdit}
              placeholder={t("nb.notes.textPlaceholder")}
              className="resize-y"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  save();
                }
              }}
            />
          </Field>
        </form>
      </Dialog>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={t("nb.notes.delete")}
        description={note ? t("nb.notes.deleteConfirm", { name: note.title || t("nb.notes.untitled") }) : ""}
        danger
        confirmLabel={t("common.delete")}
        onConfirm={async () => {
          if (!note) return;
          try {
            await api.del(`/notebooks/${nbId}/notes/${note.id}`);
            qc.setQueryData<NotebookDetail>(key, (d) =>
              d ? { ...d, notes: d.notes.filter((n) => n.id !== note.id), note_count: Math.max(0, d.note_count - 1) } : d,
            );
            qc.invalidateQueries({ queryKey: key });
            qc.invalidateQueries({ queryKey: nbKeys.list });
            toast.success(t("nb.notes.deleted"));
            onClose();
          } catch (e) {
            toastError(e);
          }
        }}
      />
    </>
  );
}

export function NotesColumn({
  nb,
  canEdit,
  onOpen,
  className,
}: {
  nb: NotebookDetail;
  canEdit: boolean;
  onOpen: (target: NoteTarget) => void;
  className?: string;
}) {
  const { t } = useTranslation();
  return (
    <Column
      title={t("nb.notes.title")}
      count={nb.notes.length}
      className={className}
      actions={
        canEdit && (
          <Button variant="soft" size="sm" onClick={() => onOpen("new")} aria-label={t("nb.notes.addLabel")}>
            <Plus />
            {t("nb.notes.add")}
          </Button>
        )
      }
      footer={
        <p className="flex shrink-0 items-start gap-1.5 border-t border-border px-3 py-2 text-[11px] text-muted-foreground">
          <Info className="mt-px size-3 shrink-0" aria-hidden />
          {t("nb.notes.hint")}
        </p>
      }
    >
      {nb.notes.length === 0 ? (
        <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
          <div className="rounded-xl bg-muted p-2.5 text-muted-foreground">
            <StickyNote className="size-5" />
          </div>
          <p className="text-sm text-muted-foreground">{t("nb.notes.empty")}</p>
        </div>
      ) : (
        <ul className="flex flex-col gap-2 p-2.5">
          {nb.notes.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                onClick={() => onOpen(n)}
                className="flex w-full flex-col gap-1 rounded-lg border border-border bg-card p-2.5 text-left transition hover:border-primary/50 hover:bg-accent/50"
              >
                <span className="flex w-full items-center gap-1.5">
                  <StickyNote className="size-3.5 shrink-0 text-warning" aria-hidden />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{n.title || t("nb.notes.untitled")}</span>
                </span>
                <span className="line-clamp-2 whitespace-pre-line break-words text-xs text-muted-foreground">{n.text}</span>
                <span className="text-[10px] text-muted-foreground/80">{fmtRelative(n.updated_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Column>
  );
}
