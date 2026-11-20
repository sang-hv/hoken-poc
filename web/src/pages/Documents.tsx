import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, FileUp, MoreHorizontal, Pencil, Search, Trash2, Upload, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ConfirmDialog, PageHeader, Pagination, useToastError } from "@/components/common";
import { DocStatusBadge } from "@/components/status";
import { docPageTotal, docProgress, NextAction, useDocProgressLabel } from "@/components/docProgress";
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
import { useClientPage } from "@/lib/hooks";
import type { Doc } from "@/lib/types";
import { cn, fmtRelative } from "@/lib/utils";

export function UploadDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const toastError = useToastError();
  const nav = useNavigate();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [form, setForm] = useState({ name: "", kind: "akahon", book_page_start: "1", page_from: "", page_to: "" });
  // Tên hiển thị đi theo tên file cho tới khi người dùng tự sửa ô này
  const [nameTouched, setNameTouched] = useState(false);
  const [busy, setBusy] = useState(false);

  const pick = (f: File | undefined) => {
    if (!f) return;
    setFile(f);
    if (!nameTouched) setForm((s) => ({ ...s, name: f.name.replace(/\.pdf$/i, "") }));
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
      setNameTouched(false);
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
            <Input
              value={form.name}
              maxLength={200}
              onChange={(e) => {
                setForm({ ...form, name: e.target.value });
                setNameTouched(e.target.value.trim() !== "");
              }}
            />
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

function DocTitle({ doc }: { doc: Doc }) {
  const { t } = useTranslation();
  const total = docPageTotal(doc);
  return (
    <div className="min-w-0">
      <Link to={`/documents/${doc.id}`} className="font-medium break-words hover:text-primary">
        {doc.name}
      </Link>
      <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
        <Badge>{t(`kinds.${doc.kind}`, { defaultValue: doc.kind })}</Badge>
        <span className="whitespace-nowrap">{t("documents.pageCount", { count: total })}</span>
        <span>·</span>
        <span className="whitespace-nowrap">
          {t("documents.bookPages", { from: doc.book_page_start, to: doc.book_page_start + total - 1 })}
        </span>
      </p>
      <p className="mt-0.5 truncate text-xs text-muted-foreground" title={doc.filename}>
        {doc.filename}
      </p>
    </div>
  );
}

function DocProgressBar({ doc }: { doc: Doc }) {
  const label = useDocProgressLabel();
  const p = docProgress(doc);
  return (
    <div>
      <Progress value={p} tone={doc.status === "failed" ? "danger" : p === 100 ? "success" : "primary"} />
      <p className="mt-1 whitespace-nowrap text-[11px] text-muted-foreground">{label(doc)}</p>
    </div>
  );
}

function EnabledSwitch({ doc, onToggle }: { doc: Doc; onToggle: (enabled: boolean) => void }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  return (
    <Switch
      checked={doc.enabled}
      disabled={!can("reviewer")}
      onCheckedChange={onToggle}
      aria-label={t("common.enabled")}
    />
  );
}

function RowMenu({ doc, onRename, onDelete }: { doc: Doc; onRename: (d: Doc) => void; onDelete: (d: Doc) => void }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  if (!can("reviewer")) return null;
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <Button variant="ghost" size="iconSm" aria-label={t("common.actions")}>
          <MoreHorizontal />
        </Button>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownItem onSelect={() => onRename(doc)}>
          <Pencil />
          {t("common.rename")}
        </DropdownItem>
        {can("admin") && (
          <DropdownItem className="text-danger" onSelect={() => onDelete(doc)}>
            <Trash2 />
            {t("common.delete")}
          </DropdownItem>
        )}
      </DropdownContent>
    </Dropdown>
  );
}

/** Đổi tên hiển thị của tài liệu (PATCH name). Dùng ở danh sách và trang chi tiết. */
export function RenameDialog({ doc, onClose }: { doc: Doc | null; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastId, setLastId] = useState<string | null>(null);
  if (doc && doc.id !== lastId) {
    setLastId(doc.id);
    setName(doc.name);
  }
  const save = async () => {
    if (!doc) return;
    setBusy(true);
    try {
      await api.patch(`/documents/${doc.id}`, { name: name.trim() });
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["document", doc.id] });
      toast.success(t("common.saved"));
      setLastId(null);
      onClose();
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={!!doc}
      onOpenChange={(o) => {
        if (!o) {
          setLastId(null);
          onClose();
        }
      }}
      title={t("documents.renameTitle")}
      className="max-w-md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={save} loading={busy} disabled={!name.trim() || name.trim() === doc?.name}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        <Field label={t("upload.name")}>
          <Input value={name} maxLength={200} autoFocus onChange={(e) => setName(e.target.value)} />
        </Field>
      </form>
    </Dialog>
  );
}

type StatusGroup = "all" | "action" | "running" | "indexed" | "failed";
const RUNNING_STATUSES = ["processing", "stitching", "chunking", "indexing"];
const ACTION_STATUSES = ["ocr_review", "ready_for_chunking", "chunk_review"];
const PAGE_SIZE = 20;

function inGroup(d: Doc, g: StatusGroup) {
  const failed = d.status === "failed" || (d.stats.failed ?? 0) > 0;
  if (g === "failed") return failed;
  if (g === "action") return failed || ACTION_STATUSES.includes(d.status);
  if (g === "running") return RUNNING_STATUSES.includes(d.status);
  if (g === "indexed") return d.status === "indexed";
  return true;
}

export default function DocumentsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const toastError = useToastError();
  const [open, setOpen] = useState(false);
  const [params, setParams] = useSearchParams();
  const filter = params.get("q") ?? "";
  const group = (params.get("status") ?? "all") as StatusGroup;
  const kind = params.get("kind") ?? "all";
  const pageNo = Number(params.get("page") ?? "1") || 1;
  /** Đổi một tham số lọc trên URL (giữ khi quay lại trang); đổi bộ lọc thì về trang 1. */
  const setParam = (key: string, value: string, empty = "") => {
    const next = new URLSearchParams(params);
    if (value === empty) next.delete(key);
    else next.set(key, value);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: true });
  };
  const [toDelete, setToDelete] = useState<Doc | null>(null);
  const [toRename, setToRename] = useState<Doc | null>(null);
  const docs = useQuery({ queryKey: ["documents"], queryFn: () => api.get<Doc[]>("/documents"), refetchInterval: 4000 });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api.patch(`/documents/${id}`, { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
    onError: toastError,
  });
  const all = useMemo(() => docs.data ?? [], [docs.data]);
  const list = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return all.filter(
      (d) =>
        (!needle || `${d.name} ${d.filename}`.toLowerCase().includes(needle)) &&
        (kind === "all" || d.kind === kind) &&
        inGroup(d, group),
    );
  }, [all, filter, kind, group]);
  const paged = useClientPage(list, pageNo, PAGE_SIZE);
  const filtered = !!filter || group !== "all" || kind !== "all";
  const groups: StatusGroup[] = ["all", "action", "running", "indexed", "failed"];

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
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <Input
            type="search"
            placeholder={t("documents.searchPlaceholder")}
            aria-label={t("documents.searchPlaceholder")}
            value={filter}
            onChange={(e) => setParam("q", e.target.value)}
            className="w-full sm:max-w-xs sm:flex-1"
          />
          <Select
            className="w-[calc(50%-0.25rem)] sm:w-52"
            aria-label={t("common.status")}
            value={group}
            onValueChange={(v) => setParam("status", v, "all")}
            options={groups.map((g) => ({
              value: g,
              label: g === "all" ? t("documents.groups.all") : `${t(`documents.groups.${g}`)} (${all.filter((d) => inGroup(d, g)).length})`,
            }))}
          />
          <Select
            className="w-[calc(50%-0.25rem)] sm:w-44"
            aria-label={t("documents.kind")}
            value={kind}
            onValueChange={(v) => setParam("kind", v, "all")}
            options={[
              { value: "all", label: t("documents.allKinds") },
              ...["akahon", "midorihon", "other"].map((k) => ({ value: k, label: t(`kinds.${k}`) })),
            ]}
          />
          {filtered && (
            <Button variant="ghost" size="sm" onClick={() => setParams({}, { replace: true })}>
              <X />
              {t("common.clearFilters")}
            </Button>
          )}
        </div>
        {docs.isLoading && (
          <div className="flex flex-col gap-3 p-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        )}
        {docs.data && list.length === 0 && filtered && (
          <EmptyState
            icon={<Search />}
            title={t("common.noMatch")}
            action={
              <Button variant="soft" onClick={() => setParams({}, { replace: true })}>
                <X />
                {t("common.clearFilters")}
              </Button>
            }
          />
        )}
        {docs.data && list.length === 0 && !filtered && (
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
          <>
            {/* xl+: bảng (dưới xl nội dung còn < ~980px, bảng 7 cột bị ép) */}
            <div className="hidden overflow-x-auto xl:block">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="px-4 py-2.5 font-medium">{t("common.name")}</th>
                    <th className="px-3 py-2.5 font-medium">{t("common.status")}</th>
                    <th className="w-44 px-3 py-2.5 font-medium">{t("documents.progress")}</th>
                    <th className="px-3 py-2.5 font-medium">{t("documents.nextStep")}</th>
                    <th className="px-3 py-2.5 font-medium">
                      <Tip content={t("documents.enabledHint")}>
                        <span>{t("common.enabled")}</span>
                      </Tip>
                    </th>
                    <th className="whitespace-nowrap px-3 py-2.5 font-medium">{t("common.updated")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {paged.items.map((d) => (
                    <tr key={d.id} className="hover:bg-accent/40">
                      <td className="min-w-56 px-4 py-3">
                        <DocTitle doc={d} />
                      </td>
                      <td className="px-3 py-3">
                        <DocStatusBadge status={d.status} />
                      </td>
                      <td className="min-w-40 px-3 py-3">
                        <DocProgressBar doc={d} />
                      </td>
                      <td className="px-3 py-3">
                        <NextAction doc={d} />
                      </td>
                      <td className="px-3 py-3">
                        <EnabledSwitch doc={d} onToggle={(enabled) => toggle.mutate({ id: d.id, enabled })} />
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-muted-foreground">{fmtRelative(d.updated_at)}</td>
                      <td className="px-2 py-3 text-right">
                        <RowMenu doc={d} onRename={setToRename} onDelete={setToDelete} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* < xl: mỗi tài liệu một khối; từ sm chia 2 cột (thông tin | tiến độ + việc tiếp theo) */}
            <ul className="divide-y divide-border xl:hidden">
              {paged.items.map((d) => (
                <li key={d.id} className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-start sm:gap-6">
                  <div className="flex min-w-0 flex-1 flex-col gap-2">
                    <div className="flex items-start justify-between gap-3">
                      <DocTitle doc={d} />
                      <span className="sm:hidden">
                        <RowMenu doc={d} onRename={setToRename} onDelete={setToDelete} />
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <DocStatusBadge status={d.status} />
                      <span className="text-xs text-muted-foreground">{fmtRelative(d.updated_at)}</span>
                    </div>
                  </div>
                  <div className="flex flex-col gap-2.5 sm:w-64 sm:shrink-0">
                    <DocProgressBar doc={d} />
                    <div className="flex items-center justify-between gap-3">
                      <NextAction doc={d} />
                      <EnabledSwitch doc={d} onToggle={(enabled) => toggle.mutate({ id: d.id, enabled })} />
                    </div>
                  </div>
                  <span className="hidden sm:block">
                    <RowMenu doc={d} onRename={setToRename} onDelete={setToDelete} />
                  </span>
                </li>
              ))}
            </ul>
            <Pagination page={paged.page} size={PAGE_SIZE} total={paged.total} onPage={(p) => setParam("page", String(p), "1")} />
          </>
        )}
      </Card>
      <UploadDialog open={open} onOpenChange={setOpen} />
      <RenameDialog doc={toRename} onClose={() => setToRename(null)} />
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
