/** ライブラリ — danh sách sổ tay (frontend B1). */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, FileText, MoreHorizontal, Pencil, Plus, StickyNote, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ConfirmDialog, PageHeader, useErrorText, useToastError } from "@/components/common";
import {
  Button,
  Card,
  Dialog,
  Dropdown,
  DropdownContent,
  DropdownItem,
  DropdownTrigger,
  EmptyState,
  Field,
  Input,
  Skeleton,
} from "@/components/ui";
import { nbKeys } from "@/components/v2/notebook/shared";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime, fmtRelative } from "@/lib/utils";
import type { NotebookSummary } from "@/lib/v2types";

/** Dialog tạo mới (target = "new") hoặc đổi tên (target = sổ tay). */
function NameDialog({
  target,
  onClose,
}: {
  target: NotebookSummary | "new" | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const nav = useNavigate();
  const toastError = useToastError();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const nb = target && target !== "new" ? target : null;

  useEffect(() => {
    if (target) setName(nb?.name ?? "");
  }, [target]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async () => {
    const n = name.trim();
    if (!n) return;
    setBusy(true);
    try {
      if (nb) {
        await api.patch<NotebookSummary>(`/notebooks/${nb.id}`, { name: n });
        qc.invalidateQueries({ queryKey: nbKeys.detail(nb.id) });
        toast.success(t("nb.library.renamed"));
      } else {
        const created = await api.post<NotebookSummary>("/notebooks", { name: n });
        toast.success(t("nb.library.created"));
        nav(`/notebooks/${created.id}`);
      }
      qc.invalidateQueries({ queryKey: nbKeys.list });
      onClose();
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={!!target}
      onOpenChange={(o) => !o && onClose()}
      title={nb ? t("nb.library.renameTitle") : t("nb.library.createTitle")}
      description={nb ? undefined : t("nb.library.createHint")}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={submit} loading={busy} disabled={!name.trim()}>
            {nb ? t("common.save") : t("nb.library.createAction")}
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <Field label={t("nb.library.nameLabel")}>
          <Input
            autoFocus
            value={name}
            maxLength={200}
            placeholder={t("nb.library.namePlaceholder")}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
      </form>
    </Dialog>
  );
}

function NotebookCard({
  nb,
  canEdit,
  onRename,
  onDelete,
}: {
  nb: NotebookSummary;
  canEdit: boolean;
  onRename: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Card className="group relative flex w-full flex-col gap-4 p-4 transition hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
      <div className="flex items-start justify-between gap-2">
        <div className="flex size-10 items-center justify-center rounded-xl bg-primary-soft text-primary">
          <BookOpen className="size-5" aria-hidden />
        </div>
        {canEdit && (
          <Dropdown>
            <DropdownTrigger asChild>
              <Button
                variant="ghost"
                size="iconSm"
                aria-label={t("nb.library.menu")}
                className="relative z-10 -mr-1 -mt-1 text-muted-foreground"
              >
                <MoreHorizontal />
              </Button>
            </DropdownTrigger>
            <DropdownContent>
              <DropdownItem onSelect={onRename}>
                <Pencil />
                {t("common.rename")}
              </DropdownItem>
              <DropdownItem onSelect={onDelete} className="text-danger [&_svg]:text-danger">
                <Trash2 />
                {t("common.delete")}
              </DropdownItem>
            </DropdownContent>
          </Dropdown>
        )}
      </div>
      <div className="min-w-0">
        {/* Link phủ cả thẻ (after:inset-0) để bấm đâu cũng mở, nút menu nằm trên (z-10) */}
        <Link
          to={`/notebooks/${nb.id}`}
          className="line-clamp-2 break-words font-semibold leading-snug outline-none after:absolute after:inset-0 after:rounded-xl focus-visible:after:ring-2 focus-visible:after:ring-ring group-hover:text-primary"
        >
          {nb.name}
        </Link>
      </div>
      <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <FileText className="size-3.5" aria-hidden />
          {t("nb.library.sourceCount", { count: nb.source_count })}
        </span>
        <span className="inline-flex items-center gap-1">
          <StickyNote className="size-3.5" aria-hidden />
          {t("nb.library.noteCount", { count: nb.note_count })}
        </span>
        <span className="ml-auto" title={fmtDateTime(nb.updated_at)}>
          {t("nb.library.updated", { when: fmtRelative(nb.updated_at) })}
        </span>
      </div>
    </Card>
  );
}

export default function LibraryPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const toastError = useToastError();
  const errText = useErrorText();
  const canEdit = can("reviewer");
  const [dialog, setDialog] = useState<NotebookSummary | "new" | null>(null);
  const [toDelete, setToDelete] = useState<NotebookSummary | null>(null);
  const q = useQuery({
    queryKey: nbKeys.list,
    queryFn: () => api.get<NotebookSummary[]>("/notebooks"),
  });
  const list = [...(q.data ?? [])].sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));

  const createBtn = canEdit && (
    <Button onClick={() => setDialog("new")}>
      <Plus />
      {t("nb.library.create")}
    </Button>
  );

  return (
    <>
      <PageHeader title={t("nb.library.title")} subtitle={t("nb.library.subtitle")} actions={list.length > 0 && createBtn} />
      {q.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-40 rounded-xl" />
          ))}
        </div>
      ) : q.isError ? (
        <Card>
          <EmptyState
            icon={<BookOpen />}
            title={t("nb.library.loadError")}
            hint={errText(q.error)}
            action={
              <Button variant="outline" onClick={() => q.refetch()}>
                {t("common.retry")}
              </Button>
            }
          />
        </Card>
      ) : list.length === 0 ? (
        <Card>
          <EmptyState icon={<BookOpen />} title={t("nb.library.emptyTitle")} hint={t("nb.library.emptyHint")} action={createBtn} />
        </Card>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {canEdit && (
            <li>
              <button
                type="button"
                onClick={() => setDialog("new")}
                className="flex h-full min-h-40 w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-border text-sm font-medium text-muted-foreground transition hover:border-primary/60 hover:bg-accent hover:text-primary"
              >
                <Plus className="size-6" aria-hidden />
                {t("nb.library.create")}
              </button>
            </li>
          )}
          {list.map((nb) => (
            <li key={nb.id} className="flex">
              <NotebookCard
                nb={nb}
                canEdit={canEdit}
                onRename={() => setDialog(nb)}
                onDelete={() => setToDelete(nb)}
              />
            </li>
          ))}
        </ul>
      )}
      <NameDialog target={dialog} onClose={() => setDialog(null)} />
      <ConfirmDialog
        open={!!toDelete}
        onOpenChange={(o) => !o && setToDelete(null)}
        title={t("nb.library.deleteTitle")}
        description={toDelete ? t("nb.library.deleteConfirm", { name: toDelete.name }) : ""}
        danger
        confirmLabel={t("common.delete")}
        onConfirm={async () => {
          const nb = toDelete!;
          try {
            await api.del(`/notebooks/${nb.id}`);
            qc.setQueryData<NotebookSummary[]>(nbKeys.list, (l) => l?.filter((x) => x.id !== nb.id));
            qc.removeQueries({ queryKey: nbKeys.detail(nb.id) });
            qc.invalidateQueries({ queryKey: nbKeys.list });
            toast.success(t("nb.library.deleted"));
          } catch (e) {
            toastError(e);
          }
        }}
      />
    </>
  );
}
