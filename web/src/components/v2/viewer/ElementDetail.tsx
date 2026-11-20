import { markdown as mdLang } from "@codemirror/lang-markdown";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import CodeMirror, { EditorView } from "@uiw/react-codemirror";
import { Braces, Check, ChevronLeft, ImageOff, Pencil, Save, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Markdown, useToastError } from "@/components/common";
import { Button, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { Element, PageElements } from "@/lib/v2types";
import { cn, fmtDateTime } from "@/lib/utils";
import { PromptDialog } from "./parts";
import { LabelChip, OrderBadge, StatusChip, WeakChip, elementImageUrl, invalidateAfterEdit, vk } from "./shared";

function Crop({ docId, page, el }: { docId: string; page: number; el: Element }) {
  const { t } = useTranslation();
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");
  return (
    <div className="relative flex min-h-16 items-center justify-center overflow-hidden rounded-lg border border-border bg-white p-2">
      {state === "loading" && <Skeleton className="absolute inset-2" />}
      {state === "error" ? (
        <p className="flex items-center gap-2 py-4 text-xs text-muted-foreground">
          <ImageOff className="size-4" aria-hidden />
          {t("viewer.detail.noCrop")}
        </p>
      ) : (
        <img
          src={elementImageUrl(docId, page, el.id)}
          alt={t("viewer.detail.cropAlt", { order: el.order })}
          onLoad={() => setState("ok")}
          onError={() => setState("error")}
          className={cn("max-h-80 max-w-full object-contain", state !== "ok" && "opacity-0")}
        />
      )}
    </div>
  );
}

function RawJson({ docId, page, eid }: { docId: string; page: number; eid: string }) {
  const { t } = useTranslation();
  const raw = useQuery({
    queryKey: vk.raw(docId, page, eid),
    queryFn: () => api.get<unknown>(`/documents/${docId}/pages/${page}/elements/${eid}/raw`),
    staleTime: 30_000,
    retry: false,
  });
  const text = useMemo(() => (raw.data === undefined ? "" : JSON.stringify(raw.data, null, 2)), [raw.data]);
  if (raw.isLoading) return <Skeleton className="h-32" />;
  if (raw.isError) return <p className="text-xs text-muted-foreground">{t("viewer.detail.rawMissing")}</p>;
  return (
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-border bg-muted p-3 font-mono text-[11px] leading-relaxed">
      {text}
    </pre>
  );
}

function Section({ title, children }: { title: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

/** Chi tiết một phần tử: ảnh cắt từ bản gốc ↔ kết quả đọc; sửa tay, đọc lại bằng AI, xác nhận, xem JSON. */
export function ElementDetail({
  docId,
  page,
  el,
  canEdit,
  onBack,
}: {
  docId: string;
  page: number;
  el: Element | undefined;
  canEdit: boolean;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<"save" | "accept" | null>(null);
  const [rereadOpen, setRereadOpen] = useState(false);
  const [showJson, setShowJson] = useState(false);

  useEffect(() => {
    setEditing(false);
    setShowJson(false);
  }, [el?.id]);

  /** Ghi phần tử backend trả về vào cache của trang ngay, rồi làm mới phần phụ thuộc. */
  const applyResult = (next: Element | undefined) => {
    if (next?.id)
      qc.setQueryData<PageElements>(vk.elements(docId, page), (old) =>
        old ? { ...old, elements: old.elements.map((e) => (e.id === next.id ? next : e)) } : old,
      );
    qc.removeQueries({ queryKey: vk.raw(docId, page, el?.id ?? "") });
    invalidateAfterEdit(qc, docId, page);
  };

  if (!el)
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center border-b border-border px-2 py-2">
          <Button variant="ghost" size="sm" onClick={onBack}>
            <ChevronLeft />
            {t("viewer.detail.back")}
          </Button>
        </div>
        <p className="p-6 text-sm text-muted-foreground">{t("viewer.detail.notFound")}</p>
      </div>
    );

  const base = `/documents/${docId}/pages/${page}/elements/${el.id}`;
  const save = async () => {
    setBusy("save");
    try {
      const next = await api.put<Element>(base, { text: draft });
      applyResult(next);
      setEditing(false);
      toast.success(t("viewer.detail.saved"));
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(null);
    }
  };
  const accept = async () => {
    setBusy("accept");
    try {
      applyResult(await api.post<Element>(`${base}/accept`));
      toast.success(t("viewer.detail.acceptedDone"));
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(null);
    }
  };
  const reread = async (prompt: string) => {
    try {
      applyResult(await api.post<Element>(`${base}/reread`, prompt ? { prompt } : {}));
      toast.success(t("viewer.detail.rereadDone"));
    } catch (e) {
      toastError(e);
      throw e;
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-2 py-2">
        <Button variant="ghost" size="iconSm" onClick={onBack} aria-label={t("viewer.detail.back")}>
          <ChevronLeft />
        </Button>
        <OrderBadge label={el.label} order={el.order} />
        <LabelChip label={el.label} />
        <span className="truncate text-xs tabular-nums text-muted-foreground">
          {t("viewer.detail.where", { page, order: el.order })}
        </span>
        <div className="flex-1" />
        <StatusChip status={el.status} />
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
          <span>{t("viewer.detail.via", { src: t(`viewer.source.${el.source}`, { defaultValue: el.source }) })}</span>
          {el.confidence !== null && (
            <span className="tabular-nums">{t("viewer.detail.confidence", { v: el.confidence.toFixed(2) })}</span>
          )}
          {el.edited_by && <span>{t("viewer.detail.editedBy", { by: el.edited_by, at: fmtDateTime(el.edited_at) })}</span>}
        </div>

        {el.weak.length > 0 && (
          <Section title={t("viewer.detail.weakTitle")}>
            <div className="flex flex-wrap gap-1.5">
              {el.weak.map((w, i) => (
                <WeakChip key={i} code={w.code} severity={w.severity} detail={w.detail} muted={el.status !== "weak"} />
              ))}
            </div>
          </Section>
        )}

        <Section title={t("viewer.detail.original")}>
          <Crop key={el.id} docId={docId} page={page} el={el} />
        </Section>

        <Section title={t("viewer.detail.result")}>
          {editing ? (
            <div
              className="overflow-hidden rounded-lg border border-input focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/20"
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === "s") {
                  e.preventDefault();
                  save();
                } else if (e.key === "Escape") setEditing(false);
              }}
            >
              <CodeMirror
                value={draft}
                autoFocus
                minHeight="10rem"
                maxHeight="24rem"
                theme={document.documentElement.classList.contains("dark") ? "dark" : "light"}
                extensions={[mdLang(), EditorView.lineWrapping]}
                onChange={setDraft}
                basicSetup={{ foldGutter: false, lineNumbers: false, highlightActiveLine: false }}
              />
            </div>
          ) : el.text.trim() ? (
            <div className="rounded-lg border border-border bg-background/60 px-3 py-2">
              <Markdown text={el.text} />
            </div>
          ) : (
            <p className="rounded-lg border border-dashed border-border px-3 py-4 text-sm italic text-muted-foreground">
              {el.label === "picture" ? t("viewer.elements.noDesc") : t("viewer.detail.emptyText")}
            </p>
          )}
        </Section>

        {showJson && (
          <Section title={t("viewer.detail.json")}>
            <RawJson docId={docId} page={page} eid={el.id} />
          </Section>
        )}
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-border px-4 py-2.5">
        {editing ? (
          <>
            <Button size="sm" loading={busy === "save"} disabled={draft === el.text} onClick={save}>
              {busy !== "save" && <Save />}
              {t("viewer.detail.save")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              <X />
              {t("viewer.detail.cancel")}
            </Button>
          </>
        ) : (
          <>
            {canEdit && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setDraft(el.text);
                    setEditing(true);
                  }}
                >
                  <Pencil />
                  {t("viewer.detail.edit")}
                </Button>
                <Button variant="outline" size="sm" onClick={() => setRereadOpen(true)}>
                  <Sparkles />
                  {t("viewer.detail.reread")}
                </Button>
                {el.status === "weak" && (
                  <Button variant="soft" size="sm" loading={busy === "accept"} onClick={accept}>
                    {busy !== "accept" && <Check />}
                    {t("viewer.detail.accept")}
                  </Button>
                )}
              </>
            )}
            <div className="flex-1" />
            <Button
              variant={showJson ? "secondary" : "ghost"}
              size="sm"
              aria-pressed={showJson}
              onClick={() => setShowJson((s) => !s)}
            >
              <Braces />
              {t("viewer.detail.json")}
            </Button>
          </>
        )}
      </div>

      <PromptDialog
        open={rereadOpen}
        onOpenChange={setRereadOpen}
        title={t("viewer.reread.title")}
        description={t("viewer.reread.desc")}
        onRun={reread}
      />
    </div>
  );
}
