import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, FileUp, MoreHorizontal, Trash2, Upload } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ConfirmDialog, PageHeader, useToastError } from "@/components/common";
import { DocStatusBadge } from "@/components/status";
import {
  Badge,
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
  Progress,
  Select,
  Skeleton,
  Switch,
  Tip,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Doc } from "@/lib/types";
import { cn, fmtRelative, pct } from "@/lib/utils";

export function UploadDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const toastError = useToastError();
  const nav = useNavigate();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [form, setForm] = useState({ name: "", kind: "akahon", book_page_start: "1", page_from: "", page_to: "" });
  const [busy, setBusy] = useState(false);

  const pick = (f: File | undefined) => {
    if (!f) return;
    setFile(f);
    if (!form.name) setForm((s) => ({ ...s, name: f.name.replace(/\.pdf$/i, "") }));
  };

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("name", form.name);
      fd.append("kind", form.kind);
      fd.append("book_page_start", form.book_page_start || "1");
      if (form.page_from) fd.append("page_from", form.page_from);
      if (form.page_to) fd.append("page_to", form.page_to);
      const doc = await api.post<Doc>("/documents", fd);
      qc.invalidateQueries({ queryKey: ["documents"] });
      onOpenChange(false);
      setFile(null);
      setForm({ name: "", kind: "akahon", book_page_start: "1", page_from: "", page_to: "" });
      nav(`/documents/${doc.id}`);
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("upload.title")}
      description={t("upload.publicOnly")}
      className="max-w-xl"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={submit} disabled={!file} loading={busy}>
            <Upload />
            {busy ? t("upload.uploading") : t("upload.start")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
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
            pick(e.dataTransfer.files[0]);
          }}
          className={cn(
            "flex flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition",
            drag ? "border-primary bg-primary-soft" : "border-border hover:border-primary/60 hover:bg-accent",
          )}
        >
          <FileUp className="size-7 text-primary" />
          {file ? (
            <span className="text-sm font-medium">
              {file.name} <span className="text-muted-foreground">({(file.size / 1024 / 1024).toFixed(1)} MB)</span>
            </span>
          ) : (
            <span className="text-sm text-muted-foreground">{t("upload.drop")}</span>
          )}
          <input
            ref={input}
            type="file"
            accept="application/pdf,.pdf"
            className="hidden"
            onChange={(e) => pick(e.target.files?.[0])}
          />
        </button>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label={t("upload.name")} className="sm:col-span-2">
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label={t("upload.kind")}>
            <Select
              value={form.kind}
              onValueChange={(v) => setForm({ ...form, kind: v })}
              options={["akahon", "midorihon", "other"].map((k) => ({ value: k, label: t(`kinds.${k}`) }))}
            />
          </Field>
          <Field label={t("upload.bookPageStart")} hint={t("upload.bookPageHint")}>
            <Input
              type="number"
              min={1}
              value={form.book_page_start}
              onChange={(e) => setForm({ ...form, book_page_start: e.target.value })}
            />
          </Field>
          <Field label={t("upload.pageFrom")} hint={t("upload.rangeHint")}>
            <Input type="number" min={1} value={form.page_from} onChange={(e) => setForm({ ...form, page_from: e.target.value })} />
          </Field>
          <Field label={t("upload.pageTo")}>
            <Input type="number" min={1} value={form.page_to} onChange={(e) => setForm({ ...form, page_to: e.target.value })} />
          </Field>
        </div>
      </div>
    </Dialog>
  );
}

export function docProgress(doc: Doc) {
  const total = doc.page_to - doc.page_from + 1;
  const s = doc.stats;
  if (["indexed"].includes(doc.status)) return 100;
  if (["chunk_review", "indexing"].includes(doc.status))
    return 70 + Math.round((pct(s.chunks_approved ?? 0, s.chunks ?? 1) * 25) / 100);
  if (["ready_for_chunking", "chunking"].includes(doc.status)) return 65;
  const processed = total - (s.queued ?? 0) - (s.docling ?? 0) - (s.routed ?? 0) - (s.cu ?? 0);
  return Math.round((processed / total) * 30 + ((s.approved ?? 0) / total) * 35);
}

export default function DocumentsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const toastError = useToastError();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [toDelete, setToDelete] = useState<Doc | null>(null);
  const docs = useQuery({ queryKey: ["documents"], queryFn: () => api.get<Doc[]>("/documents"), refetchInterval: 4000 });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api.patch(`/documents/${id}`, { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
    onError: toastError,
  });
  const list = useMemo(
    () => (docs.data ?? []).filter((d) => d.name.toLowerCase().includes(filter.toLowerCase())),
    [docs.data, filter],
  );

  return (
    <>
      <PageHeader
        title={t("documents.title")}
        subtitle={t("documents.subtitle")}
        actions={
          can("reviewer") && (
            <Button onClick={() => setOpen(true)}>
              <Upload />
              {t("documents.upload")}
            </Button>
          )
        }
      />
      <Card>
        <div className="flex items-center gap-3 border-b border-border px-4 py-3">
          <Input
            placeholder={t("documents.searchPlaceholder")}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="max-w-xs"
          />
        </div>
        {docs.isLoading && (
          <div className="flex flex-col gap-3 p-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        )}
        {docs.data && list.length === 0 && (
          <EmptyState
            icon={<FileText />}
            title={t("documents.empty")}
            hint={t("documents.emptyHint")}
            action={
              can("reviewer") && (
                <Button variant="soft" onClick={() => setOpen(true)}>
                  <Upload />
                  {t("documents.upload")}
                </Button>
              )
            }
          />
        )}
        {list.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="px-4 py-2.5 font-medium">{t("common.name")}</th>
                  <th className="px-4 py-2.5 font-medium">{t("documents.kind")}</th>
                  <th className="px-4 py-2.5 font-medium">{t("documents.pages")}</th>
                  <th className="px-4 py-2.5 font-medium">{t("common.status")}</th>
                  <th className="w-48 px-4 py-2.5 font-medium">{t("documents.progress")}</th>
                  <th className="px-4 py-2.5 font-medium">
                    <Tip content={t("documents.enabledHint")}>
                      <span>{t("common.enabled")}</span>
                    </Tip>
                  </th>
                  <th className="px-4 py-2.5 font-medium">{t("common.updated")}</th>
                  <th />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {list.map((d) => {
                  const total = d.page_to - d.page_from + 1;
                  const p = docProgress(d);
                  return (
                    <tr key={d.id} className="hover:bg-accent/40">
                      <td className="px-4 py-3">
                        <Link to={`/documents/${d.id}`} className="font-medium hover:text-primary">
                          {d.name}
                        </Link>
                        <p className="text-xs text-muted-foreground">{d.filename}</p>
                      </td>
                      <td className="px-4 py-3">
                        <Badge>{t(`kinds.${d.kind}`, { defaultValue: d.kind })}</Badge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {total}
                        <span className="block text-xs">
                          {t("documents.bookPages", { from: d.book_page_start, to: d.book_page_start + total - 1 })}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <DocStatusBadge status={d.status} />
                      </td>
                      <td className="px-4 py-3">
                        <Progress value={p} tone={d.status === "failed" ? "danger" : p === 100 ? "success" : "primary"} />
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          {t("detail.reviewed", { n: d.stats.approved ?? 0, total })}
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        <Switch
                          checked={d.enabled}
                          disabled={!can("reviewer")}
                          onCheckedChange={(v) => toggle.mutate({ id: d.id, enabled: v })}
                        />
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{fmtRelative(d.updated_at)}</td>
                      <td className="px-2 py-3 text-right">
                        {can("admin") && (
                          <Dropdown>
                            <DropdownTrigger asChild>
                              <Button variant="ghost" size="iconSm">
                                <MoreHorizontal />
                              </Button>
                            </DropdownTrigger>
                            <DropdownContent>
                              <DropdownItem className="text-danger" onSelect={() => setToDelete(d)}>
                                <Trash2 />
                                {t("common.delete")}
                              </DropdownItem>
                            </DropdownContent>
                          </Dropdown>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <UploadDialog open={open} onOpenChange={setOpen} />
      <ConfirmDialog
        open={!!toDelete}
        onOpenChange={(o) => !o && setToDelete(null)}
        title={t("common.delete")}
        description={toDelete ? t("documents.deleteConfirm", { name: toDelete.name }) : ""}
        danger
        confirmLabel={t("common.delete")}
        onConfirm={async () => {
          try {
            await api.del(`/documents/${toDelete!.id}`);
            toast.success(t("common.saved"));
            qc.invalidateQueries({ queryKey: ["documents"] });
          } catch (e) {
            toastError(e);
          }
        }}
      />
    </>
  );
}
