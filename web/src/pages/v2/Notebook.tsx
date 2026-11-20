/** ノートブック — 3 cột: nguồn / ghi chú / chat Agentic RAG (frontend B1). */
import { useQueryClient } from "@tanstack/react-query";
import { BookOpen, ChevronLeft, Pencil } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useErrorText, useToastError } from "@/components/common";
import { Button, buttonVariants, EmptyState, Input, Skeleton } from "@/components/ui";
import { ChatColumn } from "@/components/v2/notebook/ChatColumn";
import { NoteDialog, NotesColumn, type NoteTarget } from "@/components/v2/notebook/NotesColumn";
import { nbKeys, UsagePill, useNotebook } from "@/components/v2/notebook/shared";
import { SourcesColumn } from "@/components/v2/notebook/SourcesColumn";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import type { NotebookDetail, NotebookSummary } from "@/lib/v2types";

/** Tên sổ tay: bấm để sửa tại chỗ (Enter lưu, Esc huỷ, rời ô = lưu). */
function NotebookTitle({ nb, canEdit }: { nb: NotebookDetail; canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(nb.name);
  const done = useRef(false);

  useEffect(() => {
    if (!editing) setValue(nb.name);
  }, [nb.name, editing]);

  const commit = async () => {
    if (done.current) return;
    done.current = true;
    setEditing(false);
    const name = value.trim();
    if (!name || name === nb.name) return;
    qc.setQueryData<NotebookDetail>(nbKeys.detail(nb.id), (d) => (d ? { ...d, name } : d));
    try {
      await api.patch<NotebookSummary>(`/notebooks/${nb.id}`, { name });
      qc.invalidateQueries({ queryKey: nbKeys.list });
      toast.success(t("nb.library.renamed"));
    } catch (e) {
      qc.setQueryData<NotebookDetail>(nbKeys.detail(nb.id), (d) => (d ? { ...d, name: nb.name } : d));
      toastError(e);
    }
  };

  if (editing) {
    return (
      <Input
        autoFocus
        value={value}
        maxLength={200}
        aria-label={t("nb.top.nameLabel")}
        className="h-8 max-w-md text-base font-semibold"
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.nativeEvent.isComposing) {
            e.preventDefault();
            commit();
          } else if (e.key === "Escape") {
            done.current = true;
            setEditing(false);
          }
        }}
      />
    );
  }
  if (!canEdit) return <h1 className="min-w-0 truncate text-base font-semibold">{nb.name}</h1>;
  return (
    <h1 className="min-w-0">
      <button
        type="button"
        title={t("nb.top.renameHint")}
        onClick={() => {
          done.current = false;
          setValue(nb.name);
          setEditing(true);
        }}
        className="group flex min-w-0 max-w-full items-center gap-1.5 rounded-md px-1.5 py-0.5 text-left text-base font-semibold hover:bg-accent"
      >
        <span className="truncate">{nb.name}</span>
        <Pencil className="size-3.5 shrink-0 text-muted-foreground opacity-0 transition group-hover:opacity-100" aria-hidden />
      </button>
    </h1>
  );
}

function TopBar({ children }: { children?: React.ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-card px-3 lg:px-4">
      <Link to="/library" className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "shrink-0 text-muted-foreground")}>
        <ChevronLeft />
        {t("nb.top.back")}
      </Link>
      <span className="h-5 w-px shrink-0 bg-border" aria-hidden />
      {children}
    </div>
  );
}

export default function NotebookPage() {
  const { t } = useTranslation();
  const { nbId = "" } = useParams();
  const { can } = useAuth();
  const errText = useErrorText();
  const q = useNotebook(nbId);
  const [maximized, setMaximized] = useState(false);
  const [note, setNote] = useState<NoteTarget>(null);
  const canEdit = can("reviewer");

  if (q.isLoading) {
    return (
      <div className="flex h-full flex-col">
        <TopBar>
          <Skeleton className="h-5 w-48" />
        </TopBar>
        <div className="grid min-h-0 flex-1 gap-3 p-3 lg:grid-cols-[22fr_22fr_56fr]">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-64 rounded-xl lg:h-full" />
          ))}
        </div>
      </div>
    );
  }
  if (q.isError || !q.data) {
    const notFound = q.error instanceof ApiError && q.error.status === 404;
    return (
      <div className="flex h-full flex-col">
        <TopBar />
        <EmptyState
          icon={<BookOpen />}
          title={notFound ? t("nb.top.notFound") : t("nb.top.loadError")}
          hint={notFound ? undefined : errText(q.error)}
          action={
            notFound ? (
              <Link to="/library" className={buttonVariants({ variant: "outline" })}>
                {t("nb.top.back")}
              </Link>
            ) : (
              <Button variant="outline" onClick={() => q.refetch()}>
                {t("common.retry")}
              </Button>
            )
          }
        />
      </div>
    );
  }

  const nb = q.data;
  const enabled = nb.sources.filter((s) => s.enabled).length;

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <TopBar>
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <NotebookTitle nb={nb} canEdit={canEdit} />
          <UsagePill on={enabled} total={nb.sources.length} className="shrink-0" />
        </div>
      </TopBar>
      <div
        className={cn(
          "flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3 lg:grid lg:overflow-hidden",
          maximized ? "lg:grid-cols-1" : "lg:grid-cols-[minmax(0,22fr)_minmax(0,22fr)_minmax(0,56fr)]",
        )}
      >
        {!maximized && (
          <>
            <SourcesColumn nb={nb} canEdit={canEdit} className="max-h-[32rem] lg:max-h-none" />
            <NotesColumn nb={nb} canEdit={canEdit} onOpen={setNote} className="max-h-[24rem] lg:max-h-none" />
          </>
        )}
        <ChatColumn
          nb={nb}
          canChat={canEdit}
          maximized={maximized}
          onToggleMaximize={() => setMaximized((m) => !m)}
          onOpenNote={setNote}
          className="min-h-[32rem] lg:min-h-0"
        />
      </div>
      <NoteDialog nbId={nb.id} target={note} canEdit={canEdit} onClose={() => setNote(null)} />
    </div>
  );
}
