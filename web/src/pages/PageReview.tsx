import { markdown as mdLang } from "@codemirror/lang-markdown";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import CodeMirror, { EditorView, type ReactCodeMirrorRef } from "@uiw/react-codemirror";
import { diffLines } from "diff";
import {
  AlertTriangle,
  ArrowLeft,
  Braces,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Download,
  Eye,
  FileDiff,
  History,
  Info,
  Pencil,
  RotateCcw,
  Save,
  ScanSearch,
  Sparkles,
  Undo2,
  ZoomIn,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Markdown, useToastError } from "@/components/common";
import { GradeBadge, PageStatusBadge, RouteBadge, ScoreBar } from "@/components/status";
import {
  Badge,
  Button,
  Dialog,
  Dropdown,
  DropdownContent,
  DropdownItem,
  DropdownLabel,
  DropdownTrigger,
  Kbd,
  Select,
  Skeleton,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  Tip,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useEventStream } from "@/lib/sse";
import type { Doc, JobEvent, LowConfidenceBox, Page, PageDetail } from "@/lib/types";
import { cn, fmtDateTime } from "@/lib/utils";

const BOX_COLORS: Record<string, string> = {
  table: "border-violet bg-violet/10",
  picture: "border-warning bg-warning/10",
  section_header: "border-info bg-info/5",
  title: "border-info bg-info/5",
  text: "border-primary/50",
  list_item: "border-primary/50",
};

function PageImage({
  detail,
  overlay,
  zoom,
  showLow,
  focused,
  onFocusBox,
}: {
  detail: PageDetail;
  overlay: boolean;
  zoom: number;
  showLow: boolean;
  focused: number | null;
  onFocusBox: (i: number) => void;
}) {
  const { t } = useTranslation();
  const [loaded, setLoaded] = useState(false);
  const focusRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    focusRef.current?.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
  }, [focused]);
  return (
    <div className="relative mx-auto" style={{ width: `${zoom}%` }}>
      {!loaded && <Skeleton className="aspect-[1/1.414] w-full" />}
      <img
        src={`/api/documents/${detail.doc_id}/pages/${detail.page}/image?v=${detail.updated_at}`}
        alt={t("review.page", { page: detail.page })}
        onLoad={() => setLoaded(true)}
        className={cn("w-full rounded-md border border-border bg-white shadow-sm", !loaded && "hidden")}
      />
      {loaded &&
        overlay &&
        detail.elements
          .filter((el) => el.label !== "ocr_text")
          .map((el, i) => (
          <Tip key={i} content={`${el.label}${el.class ? ` · ${el.class}` : ""}${el.removed ? " (removed)" : ""}`}>
            <div
              className={cn(
                "absolute rounded-sm border",
                el.removed ? "border-danger bg-danger/15 border-dashed" : (BOX_COLORS[el.label] ?? "border-muted-foreground/40"),
              )}
              style={{
                left: `${el.bbox[0] * 100}%`,
                top: `${el.bbox[1] * 100}%`,
                width: `${(el.bbox[2] - el.bbox[0]) * 100}%`,
                height: `${(el.bbox[3] - el.bbox[1]) * 100}%`,
              }}
            />
          </Tip>
        ))}
      {loaded &&
        showLow &&
        detail.low_confidence.boxes.map((b, i) => (
          <Tip key={`low-${i}`} content={`${b.text || b.label} · ${b.confidence.toFixed(2)} · ${t(`review.${b.source}`)}`}>
            <button
              type="button"
              ref={i === focused ? focusRef : undefined}
              onClick={() => onFocusBox(i)}
              aria-label={t("review.lowBox", { text: b.text || b.label, conf: b.confidence.toFixed(2) })}
              className={cn(
                "absolute cursor-pointer rounded-[3px] border-2 border-danger bg-danger/10 transition hover:bg-danger/25",
                i === focused && "z-10 bg-danger/25 ring-2 ring-danger ring-offset-2 ring-offset-white",
              )}
              style={{
                left: `${b.bbox[0] * 100}%`,
                top: `${b.bbox[1] * 100}%`,
                width: `${Math.max(0.4, (b.bbox[2] - b.bbox[0]) * 100)}%`,
                height: `${Math.max(0.4, (b.bbox[3] - b.bbox[1]) * 100)}%`,
              }}
            />
          </Tip>
        ))}
    </div>
  );
}

/** Vị trí của vùng confidence thấp trong nội dung editor: lấy lần xuất hiện của chữ gần `span` nhất (span trỏ vào
 *  markdown CU gốc, nội dung editor có thể đã đổi nên chỉ dùng làm gợi ý). Không thấy thì thử 6 ký tự đầu. */
function locate(text: string, box: LowConfidenceBox): [number, number] | null {
  const tryFind = (needle: string) => {
    if (!needle) return null;
    let best = -1;
    for (let at = text.indexOf(needle); at >= 0; at = text.indexOf(needle, at + 1)) {
      if (best < 0 || (box.span && Math.abs(at - box.span[0]) < Math.abs(best - box.span[0]))) best = at;
      if (!box.span) break;
    }
    return best >= 0 ? ([best, best + needle.length] as [number, number]) : null;
  };
  const words = box.text.trim();
  return tryFind(words) ?? tryFind(words.slice(0, 6));
}

/** Tab JSON: kết quả thô của Docling hoặc CU, chỉ đọc, tải về được. */
function RawJson({ docId, page, sources }: { docId: string; page: number; sources: ("docling" | "cu")[] }) {
  const { t } = useTranslation();
  const [src, setSrc] = useState(sources[0]);
  const raw = useQuery({
    queryKey: ["page-raw", docId, page, src],
    queryFn: () => api.get<unknown>(`/documents/${docId}/pages/${page}/raw/${src}`),
    enabled: !!src,
    staleTime: 60_000,
  });
  const text = useMemo(() => (raw.data === undefined ? "" : JSON.stringify(raw.data, null, 2)), [raw.data]);
  const LIMIT = 200_000;
  const download = () => {
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `page-${page}-${src}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };
  if (!src) return <p className="p-6 text-sm text-muted-foreground">{t("review.rawMissing")}</p>;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-border px-4 py-1.5 text-xs">
        <Select
          className="h-7 w-52 text-xs"
          aria-label={t("review.rawSource")}
          value={src}
          onValueChange={(v) => setSrc(v as "docling" | "cu")}
          options={sources.map((k) => ({ value: k, label: `${t(`review.${k}`)} · ${k}.json` }))}
        />
        <div className="flex-1" />
        <Button variant="ghost" size="sm" disabled={!text} onClick={download}>
          <Download />
          {t("review.download")}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {raw.isLoading && <Skeleton className="m-4 h-40" />}
        {raw.isError && <p className="p-6 text-sm text-muted-foreground">{t("review.rawMissing")}</p>}
        {text && (
          <>
            {text.length > LIMIT && (
              <p className="border-b border-border bg-warning-soft/60 px-4 py-2 text-xs">
                {t("review.rawTruncated", { n: LIMIT.toLocaleString() })}
              </p>
            )}
            <pre className="whitespace-pre-wrap break-all p-4 font-mono text-[11px] leading-relaxed">
              {text.length > LIMIT ? text.slice(0, LIMIT) : text}
            </pre>
          </>
        )}
      </div>
    </div>
  );
}

function DiffView({ before, after }: { before: string; after: string }) {
  const { t } = useTranslation();
  const parts = useMemo(() => diffLines(before, after), [before, after]);
  if (!parts.some((p) => p.added || p.removed))
    return <p className="p-6 text-sm text-muted-foreground">{t("review.noChanges")}</p>;
  return (
    <pre className="overflow-auto p-4 font-mono text-[12.5px] leading-relaxed">
      {parts.map((p, i) => (
        <span
          key={i}
          className={cn(
            "block whitespace-pre-wrap",
            p.added && "bg-success-soft text-success",
            p.removed && "bg-danger-soft text-danger line-through decoration-danger/40",
            !p.added && !p.removed && "text-muted-foreground",
          )}
        >
          {p.value
            .replace(/\n$/, "")
            .split("\n")
            .map((ln) => `${p.added ? "+ " : p.removed ? "- " : "  "}${ln}`)
            .join("\n")}
        </span>
      ))}
    </pre>
  );
}

export default function PageReviewPage() {
  const { docId = "", page: pageParam = "1" } = useParams();
  const page = Number(pageParam);
  const { t } = useTranslation();
  const { can } = useAuth();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toastError = useToastError();
  const canEdit = can("reviewer");

  const doc = useQuery({ queryKey: ["document", docId], queryFn: () => api.get<Doc>(`/documents/${docId}`) });
  const pages = useQuery({ queryKey: ["pages", docId], queryFn: () => api.get<Page[]>(`/documents/${docId}/pages`) });
  const detail = useQuery({
    queryKey: ["page", docId, page],
    queryFn: () => api.get<PageDetail>(`/documents/${docId}/pages/${page}`),
  });

  const [text, setText] = useState("");
  const [base, setBase] = useState("");
  const [tab, setTab] = useState("editor");
  const [diffWith, setDiffWith] = useState("stitched");
  const [overlay, setOverlay] = useState(false);
  const [showLow, setShowLow] = useState(true);
  const [focusIdx, setFocusIdx] = useState<number | null>(null);
  const cmRef = useRef<ReactCodeMirrorRef>(null);
  const [zoom, setZoom] = useState(100);
  const [busy, setBusy] = useState<string | null>(null);
  const [rerunOpen, setRerunOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [versionText, setVersionText] = useState<Record<number, string>>({});
  const loadedKey = useRef("");

  const d = detail.data;
  useEffect(() => {
    if (!d) return;
    const key = `${d.doc_id}:${d.page}:${d.current_version}`;
    if (loadedKey.current !== key) {
      loadedKey.current = key;
      setText(d.markdown);
      setBase(d.markdown);
    }
  }, [d]);

  const onEvent = useCallback(
    (e: JobEvent) => {
      if (e.page === page || e.step === "stitch") {
        qc.invalidateQueries({ queryKey: ["page", docId, page] });
        qc.invalidateQueries({ queryKey: ["pages", docId] });
      }
    },
    [qc, docId, page],
  );
  useEventStream(`/api/stream/documents/${docId}`, onEvent, 50);

  const dirty = text !== base;
  const list = pages.data ?? [];
  const idx = list.findIndex((p) => p.page === page);
  const prev = idx > 0 ? list[idx - 1] : undefined;
  const next = idx >= 0 && idx < list.length - 1 ? list[idx + 1] : undefined;
  const reviewable = d && ["review", "approved"].includes(d.status);
  const go = (p?: Page) => {
    if (!p) return;
    if (dirty && !confirm(t("review.unsaved"))) return;
    nav(`/documents/${docId}/pages/${p.page}`);
  };

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["page", docId, page] });
    qc.invalidateQueries({ queryKey: ["pages", docId] });
    qc.invalidateQueries({ queryKey: ["document", docId] });
  };

  const save = async () => {
    if (!dirty || !canEdit) return;
    setBusy("save");
    try {
      await api.put(`/documents/${docId}/pages/${page}/content`, { markdown: text });
      setBase(text);
      toast.success(t("common.saved"));
      refresh();
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(null);
    }
  };

  const approve = async () => {
    if (!canEdit) return;
    setBusy("approve");
    try {
      await api.post(`/documents/${docId}/pages/${page}/submit`, dirty ? { markdown: text } : {});
      setBase(text);
      toast.success(t("review.approved"));
      refresh();
      const nextPending = list.slice(idx + 1).find((p) => p.status === "review") ?? list.find((p) => p.status === "review" && p.page !== page);
      if (nextPending) nav(`/documents/${docId}/pages/${nextPending.page}`);
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(null);
    }
  };

  const reopen = async () => {
    setBusy("reopen");
    try {
      await api.post(`/documents/${docId}/pages/${page}/reopen`);
      refresh();
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(null);
    }
  };

  const rerun = async () => {
    setBusy("rerun");
    try {
      await api.post(`/documents/${docId}/pages/${page}/rerun`, { prompt });
      toast.success(t("review.rerunQueued"));
      setRerunOpen(false);
      setPrompt("");
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(null);
    }
  };

  const restore = async (v: number) => {
    try {
      await api.post(`/documents/${docId}/pages/${page}/restore/${v}`);
      refresh();
    } catch (e) {
      toastError(e);
    }
  };

  useEffect(() => {
    if (!diffWith.startsWith("v")) return;
    const v = Number(diffWith.slice(1));
    if (versionText[v] !== undefined) return;
    api
      .get<{ markdown: string }>(`/documents/${docId}/pages/${page}/versions/${v}`)
      .then((r) => setVersionText((s) => ({ ...s, [v]: r.markdown })))
      .catch(() => undefined);
  }, [diffWith, docId, page, versionText]);

  useEffect(() => {
    setVersionText({});
    setFocusIdx(null);
  }, [page]);

  const lowBoxes = d?.low_confidence?.boxes ?? [];
  /** Chọn vùng thấp thứ i: viền đậm trên ảnh và bôi chọn đoạn chữ tương ứng trong editor (nếu tìm thấy). */
  const focusBox = (i: number) => {
    const box = lowBoxes[i];
    if (!box) return;
    setShowLow(true);
    setFocusIdx(i);
    const range = locate(text, box);
    const view = cmRef.current?.view;
    if (range && view) {
      if (tab !== "editor") setTab("editor");
      view.dispatch({
        selection: { anchor: range[0], head: range[1] },
        effects: EditorView.scrollIntoView(range[0], { y: "center" }),
      });
    }
  };
  const stepLow = (delta: number) => {
    if (!lowBoxes.length) return;
    const cur = focusIdx ?? (delta > 0 ? -1 : 0);
    focusBox((cur + delta + lowBoxes.length) % lowBoxes.length);
  };
  const rawSources = d ? ((["docling", "cu"] as const).filter((k) => (k === "cu" ? d.cu_status === "done" : !!d.engine)) as ("docling" | "cu")[]) : [];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const inEditor = (e.target as HTMLElement)?.closest?.(".cm-editor, textarea, input");
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        save();
      } else if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        approve();
      } else if (!inEditor && e.key === "j") go(next);
      else if (!inEditor && e.key === "k") go(prev);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const diffBase =
    diffWith === "docling" || diffWith === "cu" || diffWith === "stitched"
      ? (d?.sources[diffWith] ?? "")
      : diffWith.startsWith("v")
        ? (versionText[Number(diffWith.slice(1))] ?? "")
        : base;

  const diffOptions = [
    ...(["stitched", "docling", "cu"] as const)
      .filter((k) => d?.sources[k])
      .map((k) => ({ value: k, label: t(`review.${k}`) })),
    ...(d?.versions ?? [])
      .slice()
      .reverse()
      .map((v) => ({ value: `v${v.v}`, label: `v${v.v} · ${t(`versionSource.${v.source}`)}` })),
  ];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 overflow-x-auto border-b border-border bg-card px-4 py-2 [&>*]:shrink-0">
        <Button variant="ghost" size="sm" onClick={() => nav(`/documents/${docId}`)}>
          <ArrowLeft />
          <span className="hidden max-w-40 truncate 2xl:inline">{doc.data?.name ?? t("review.backToDoc")}</span>
        </Button>
        <div className="flex items-center gap-1">
          <Button variant="outline" size="iconSm" disabled={!prev} onClick={() => go(prev)} aria-label={t("common.prev")}>
            <ChevronLeft />
          </Button>
          <Select
            className="h-8 w-44"
            value={String(page)}
            onValueChange={(v) => go(list.find((p) => p.page === Number(v)))}
            options={list.map((p) => ({
              value: String(p.page),
              label: (
                <span className="flex items-center gap-2">
                  <span
                    className={cn(
                      "size-2 rounded-full",
                      p.status === "approved" ? "bg-success" : p.status === "review" ? "bg-warning" : "bg-muted-foreground/40",
                    )}
                  />
                  {t("review.bookPage", { page: p.book_page })} · p{p.page}
                </span>
              ),
            }))}
          />
          <Button variant="outline" size="iconSm" disabled={!next} onClick={() => go(next)} aria-label={t("common.next")}>
            <ChevronRight />
          </Button>
        </div>
        {d && (
          <div className="flex items-center gap-1.5">
            <PageStatusBadge status={d.status} />
            <RouteBadge route={d.route} />
            <GradeBadge grade={d.scores.low_grade} />
            {dirty && <Badge tone="warning">{t("review.unsaved")}</Badge>}
          </div>
        )}
        <div className="flex-1" />
        <span className="hidden items-center gap-1 text-[11px] text-muted-foreground 2xl:flex">
          <Kbd>J</Kbd>/<Kbd>K</Kbd> · <Kbd>Ctrl+S</Kbd> · <Kbd>Ctrl+Enter</Kbd>
        </span>
        {d && d.versions.length > 0 && (
          <Dropdown>
            <DropdownTrigger asChild>
              <Button variant="ghost" size="sm">
                <History />v{d.current_version}
              </Button>
            </DropdownTrigger>
            <DropdownContent className="w-72">
              <DropdownLabel>{t("review.versions")}</DropdownLabel>
              {d.versions
                .slice()
                .reverse()
                .map((v) => (
                  <DropdownItem
                    key={v.v}
                    disabled={!canEdit || v.v === d.current_version}
                    onSelect={() => restore(v.v)}
                    className="flex-col items-start gap-0"
                  >
                    <span className="flex w-full items-center justify-between">
                      <span className="font-medium">
                        v{v.v} · {t(`versionSource.${v.source}`)}
                      </span>
                      {v.v === d.current_version ? <Check /> : <Undo2 />}
                    </span>
                    <span className="text-[11px] text-muted-foreground">
                      {v.by} · {fmtDateTime(v.at)}
                    </span>
                  </DropdownItem>
                ))}
            </DropdownContent>
          </Dropdown>
        )}
        {canEdit && reviewable && (
          <>
            <Button variant="outline" size="sm" onClick={() => setRerunOpen(true)} aria-label={t("review.rerun")} title={t("review.rerun")}>
              <Sparkles />
              <span className="hidden xl:inline">{t("review.rerun")}</span>
            </Button>
            <Button variant="outline" size="sm" onClick={save} disabled={!dirty} loading={busy === "save"} aria-label={t("review.saveDraft")} title={t("review.saveDraft")}>
              <Save />
              <span className="hidden xl:inline">{t("review.saveDraft")}</span>
            </Button>
            {d?.status === "approved" && !dirty ? (
              <Button variant="secondary" size="sm" onClick={reopen} loading={busy === "reopen"}>
                <RotateCcw />
                {t("review.reopen")}
              </Button>
            ) : (
              <Button size="sm" onClick={approve} loading={busy === "approve"}>
                <Check />
                {t("review.submit")}
              </Button>
            )}
          </>
        )}
      </div>

      {!d ? (
        <div className="grid flex-1 grid-cols-2 gap-4 p-4">
          <Skeleton className="h-full" />
          <Skeleton className="h-full" />
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-2">
          <section className="flex min-h-0 flex-col border-r border-border bg-muted/40">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-b border-border bg-card px-4 py-2 text-xs">
              <span className="font-medium">
                {t("review.page", { page: d.page })} · {t("review.bookPage", { page: d.book_page })}
              </span>
              <div className="flex-1" />
              <label className="flex items-center gap-2">
                <ScanSearch className="size-3.5" />
                {t("review.overlay")}
                <Switch checked={overlay} onCheckedChange={setOverlay} />
              </label>
              {lowBoxes.length > 0 && (
                <span className="flex items-center gap-1">
                  <label className="flex items-center gap-2" title={t("review.lowHint", { threshold: d.low_confidence.threshold })}>
                    <AlertTriangle className="size-3.5 text-danger" />
                    <span className="text-danger">{t("review.lowConfidence", { n: lowBoxes.length })}</span>
                    <Switch checked={showLow} onCheckedChange={setShowLow} />
                  </label>
                  <Button variant="ghost" size="iconSm" onClick={() => stepLow(-1)} aria-label={t("review.prevLow")}>
                    <ChevronUp />
                  </Button>
                  <Button variant="ghost" size="iconSm" onClick={() => stepLow(1)} aria-label={t("review.nextLow")}>
                    <ChevronDown />
                  </Button>
                </span>
              )}
              <label className="flex items-center gap-2">
                <ZoomIn className="size-3.5" />
                <input
                  type="range"
                  min={60}
                  max={200}
                  step={10}
                  value={zoom}
                  onChange={(e) => setZoom(Number(e.target.value))}
                  className="w-24 accent-[var(--primary)]"
                />
              </label>
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-4">
              <PageImage
                detail={d}
                overlay={overlay}
                zoom={zoom}
                showLow={showLow}
                focused={focusIdx}
                onFocusBox={focusBox}
              />
            </div>
            <details className="border-t border-border bg-card px-4 py-3 text-sm" open={d.route === "hard"}>
              <summary className="flex cursor-pointer items-center gap-2 font-medium">
                <Info className="size-4 text-muted-foreground" />
                {t("review.scores")} · {t("review.reasons")}
              </summary>
              <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <ScoreBar label="parse" value={d.scores.parse_score} />
                  <ScoreBar label="layout" value={d.scores.layout_score} />
                  <ScoreBar label="ocr" value={d.scores.ocr_score} />
                  <ScoreBar label="low" value={d.scores.low_score} />
                  <ScoreBar label="mean" value={d.scores.mean_score} />
                </div>
                <div className="flex flex-col gap-1.5 text-xs">
                  <div className="flex flex-wrap gap-1">
                    <Badge tone={d.engine === "docling" ? "primary" : "neutral"}>{d.engine}</Badge>
                    {d.cu_status && <Badge tone={d.cu_status === "done" ? "violet" : "warning"}>CU: {d.cu_status}</Badge>}
                  </div>
                  {d.route_reasons.length === 0 && <span className="text-muted-foreground">—</span>}
                  {d.route_reasons.map((r) => (
                    <span key={r} className="flex items-start gap-1.5">
                      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-violet" />
                      {t(`reasons.${r}`)}
                    </span>
                  ))}
                  {Object.keys(d.features.removed).length > 0 && (
                    <span className="text-muted-foreground">
                      {t("review.removed", {
                        items: Object.entries(d.features.removed)
                          .map(([k, v]) => `${k} ×${v}`)
                          .join(", "),
                      })}
                    </span>
                  )}
                  {d.reviewed_by && (
                    <span className="text-success">{t("review.approvedBy", { by: d.reviewed_by, at: fmtDateTime(d.reviewed_at) })}</span>
                  )}
                </div>
                {lowBoxes.length > 0 && (
                  <div className="sm:col-span-2">
                    <p className="mb-1.5 text-xs text-muted-foreground">
                      {t("review.lowList", { n: lowBoxes.length, threshold: d.low_confidence.threshold })}
                    </p>
                    <ul className="flex max-h-36 flex-col gap-0.5 overflow-auto text-xs">
                      {lowBoxes.slice(0, 200).map((b, i) => (
                        <li key={i}>
                          <button
                            type="button"
                            onClick={() => focusBox(i)}
                            className={cn(
                              "flex w-full items-center gap-2 rounded-md px-2 py-1 text-left hover:bg-accent",
                              i === focusIdx && "bg-danger-soft",
                            )}
                          >
                            <span className="w-10 shrink-0 font-mono tabular-nums text-danger">{b.confidence.toFixed(2)}</span>
                            <Badge tone={b.source === "cu" ? "violet" : "primary"}>{b.source === "cu" ? "CU" : "Docling"}</Badge>
                            <span className="truncate">{b.text || b.label}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </details>
          </section>

          <section className="flex min-h-0 flex-col">
            {!reviewable ? (
              <div className="flex flex-1 items-center justify-center p-8 text-sm text-muted-foreground">
                {d.status === "failed" ? d.error : t("review.notReady")}
              </div>
            ) : (
              <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
                <div className="flex items-center gap-3 border-b border-border bg-card px-4 py-1.5">
                  <TabsList className="h-8 p-0.5">
                    <TabsTrigger value="editor" className="py-1 text-xs">
                      <Pencil />
                      {t("review.editor")}
                    </TabsTrigger>
                    <TabsTrigger value="preview" className="py-1 text-xs">
                      <Eye />
                      {t("review.preview")}
                    </TabsTrigger>
                    <TabsTrigger value="diff" className="py-1 text-xs">
                      <FileDiff />
                      {t("review.diff")}
                    </TabsTrigger>
                    <TabsTrigger value="json" className="py-1 text-xs">
                      <Braces />
                      {t("review.json")}
                    </TabsTrigger>
                  </TabsList>
                  {tab === "diff" && (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      {t("review.diffAgainst")}
                      <Select className="h-7 w-44 text-xs" value={diffWith} onValueChange={setDiffWith} options={diffOptions} />
                    </div>
                  )}
                </div>
                <TabsContent value="editor" className="min-h-0 flex-1 overflow-hidden data-[state=inactive]:hidden">
                  <CodeMirror
                    ref={cmRef}
                    value={text}
                    height="100%"
                    className="h-full"
                    theme={document.documentElement.classList.contains("dark") ? "dark" : "light"}
                    extensions={[mdLang(), EditorView.lineWrapping]}
                    editable={canEdit}
                    onChange={setText}
                    basicSetup={{ foldGutter: false, highlightActiveLine: true }}
                  />
                </TabsContent>
                <TabsContent value="preview" className="min-h-0 flex-1 overflow-auto p-6 data-[state=inactive]:hidden">
                  <Markdown text={text} />
                  <p className="mt-6 text-xs text-muted-foreground">{t("review.figureHint")}</p>
                </TabsContent>
                <TabsContent value="diff" className="min-h-0 flex-1 overflow-auto data-[state=inactive]:hidden">
                  <DiffView before={diffBase} after={text} />
                </TabsContent>
                <TabsContent value="json" className="min-h-0 flex-1 overflow-hidden data-[state=inactive]:hidden">
                  {tab === "json" && <RawJson docId={docId} page={page} sources={rawSources} />}
                </TabsContent>
              </Tabs>
            )}
          </section>
        </div>
      )}

      <Dialog
        open={rerunOpen}
        onOpenChange={setRerunOpen}
        title={t("review.rerun")}
        description={t("review.rerunPlaceholder")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRerunOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button onClick={rerun} disabled={!prompt.trim()} loading={busy === "rerun"}>
              <Sparkles />
              {t("review.rerun")}
            </Button>
          </>
        }
      >
        <Textarea rows={5} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={t("review.rerunPlaceholder")} />
        <p className="mt-2 text-xs text-muted-foreground">
          <Link to={`/documents/${docId}?tab=jobs`} className="underline">
            {t("nav.jobs")}
          </Link>
        </p>
      </Dialog>
    </div>
  );
}
