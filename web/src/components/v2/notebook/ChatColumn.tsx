import {
  AlertTriangle,
  Bot,
  ChevronRight,
  Eraser,
  Headset,
  Loader2,
  Maximize2,
  MessageSquareText,
  Minimize2,
  Search,
  SendHorizontal,
  StickyNote,
  User,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useErrorText } from "@/components/common";
import { Button, Select, Textarea, Tip } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ChatAnswer, ChatCitation, Note, NotebookDetail } from "@/lib/v2types";
import { Column, isReady, UsagePill } from "./shared";

type Lang = "auto" | "ja" | "en" | "vi";
type Mode = "auto" | "deep";

interface Msg {
  id: number;
  role: "user" | "assistant";
  content: string;
  answer?: ChatAnswer;
  error?: string;
  pending?: boolean;
}

function pageLabel(t: (k: string, o?: Record<string, unknown>) => string, c: ChatCitation) {
  if (c.kind === "note") return t("nb.chat.citeNote");
  return c.page_to && c.page_to !== c.page_from
    ? t("nb.chat.citePages", { from: c.page_from, to: c.page_to })
    : t("nb.chat.citePage", { page: c.page_from });
}

/** Chip [n] trong câu trả lời: hover = tooltip nguồn/trang/trích đoạn; bấm = mở trang nguồn (hoặc ghi chú). */
function CiteChip({ c, onOpen }: { c: ChatCitation; onOpen: (c: ChatCitation) => void }) {
  const { t } = useTranslation();
  return (
    <Tip
      content={
        <span className="flex flex-col gap-1">
          <span className="font-semibold">
            [{c.n}] {c.doc_name} · {pageLabel(t, c)}
            {c.item_code && <span className="ml-1 font-mono opacity-80">{c.item_code}</span>}
          </span>
          {c.excerpt && <span className="line-clamp-4 opacity-90">{c.excerpt}</span>}
          {c.weak && (
            <span className="flex items-center gap-1 font-medium text-warning">
              <AlertTriangle className="size-3 shrink-0" aria-hidden />
              {t("nb.chat.weakCite")}
            </span>
          )}
          <span className="opacity-70">{c.kind === "note" ? t("nb.chat.citeOpenNote") : t("nb.chat.citeOpen")}</span>
        </span>
      }
    >
      <button
        type="button"
        onClick={() => onOpen(c)}
        aria-label={`${t("nb.chat.citeTitle", { n: c.n })}: ${c.doc_name} ${pageLabel(t, c)}${c.weak ? ` — ${t("nb.chat.weakCite")}` : ""}`}
        className={cn(
          "mx-0.5 inline-flex h-5 min-w-5 items-center justify-center gap-0.5 rounded-md px-1 align-text-top text-[11px] font-semibold transition hover:brightness-95",
          c.weak ? "bg-warning-soft text-[color:var(--warning)] dark:text-warning" : "bg-primary-soft text-primary",
        )}
      >
        {c.weak && <AlertTriangle className="size-3" aria-hidden />}
        {c.n}
      </button>
    </Tip>
  );
}

/** Câu trả lời: [n] → chip trích dẫn (nếu có trong danh sách citations). */
function AnswerText({ a, onOpen }: { a: ChatAnswer; onOpen: (c: ChatCitation) => void }) {
  const parts = a.answer.split(/(\[\d+\])/g);
  return (
    <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
      {parts.map((p, i) => {
        const m = /^\[(\d+)\]$/.exec(p);
        const c = m ? a.citations.find((x) => x.n === Number(m[1])) : undefined;
        return c ? <CiteChip key={i} c={c} onOpen={onOpen} /> : <span key={i}>{p}</span>;
      })}
    </p>
  );
}

function AnswerBlock({ a, onOpen }: { a: ChatAnswer; onOpen: (c: ChatCitation) => void }) {
  const { t } = useTranslation();
  const searches = a.steps.filter((s) => s.type === "search");
  return (
    <div className="flex flex-col gap-2.5">
      {a.handoff ? (
        <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning-soft px-3 py-2 text-sm">
          <Headset className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <span>
            <span className="font-medium">{t("nb.chat.handoff")}</span>
            <span className="block text-xs text-muted-foreground">{t(`nb.chat.reasons.${a.reason || "not_in_sources"}`)}</span>
          </span>
        </div>
      ) : (
        <AnswerText a={a} onOpen={onOpen} />
      )}
      {!a.handoff && a.citations.length > 0 && (
        <ol className="flex flex-col gap-1">
          {a.citations.map((c) => (
            <li key={c.n}>
              <button
                type="button"
                onClick={() => onOpen(c)}
                className="flex w-full min-w-0 items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-xs text-muted-foreground transition hover:bg-accent hover:text-foreground"
              >
                <span
                  className={cn(
                    "flex h-4 min-w-4 shrink-0 items-center justify-center rounded px-0.5 text-[10px] font-semibold",
                    c.weak ? "bg-warning-soft text-[color:var(--warning)] dark:text-warning" : "bg-primary-soft text-primary",
                  )}
                >
                  {c.n}
                </span>
                {c.kind === "note" && <StickyNote className="size-3 shrink-0 text-warning" aria-hidden />}
                <span className="min-w-0 truncate">{c.doc_name}</span>
                <span className="shrink-0 tabular-nums">· {pageLabel(t, c)}</span>
                {c.weak && (
                  <span className="flex shrink-0 items-center gap-0.5 text-warning" title={t("nb.chat.weakCite")}>
                    <AlertTriangle className="size-3" aria-hidden />
                    <span className="sr-only">{t("nb.chat.weakCite")}</span>
                  </span>
                )}
              </button>
            </li>
          ))}
        </ol>
      )}
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        {searches.length > 0 && (
          <details className="group min-w-0">
            <summary className="inline-flex cursor-pointer list-none items-center gap-1 hover:text-foreground [&::-webkit-details-marker]:hidden">
              <ChevronRight className="size-3 transition group-open:rotate-90" aria-hidden />
              <Search className="size-3" aria-hidden />
              {t("nb.chat.steps", { count: searches.length })}
            </summary>
            <ol className="mt-1 flex flex-col gap-0.5 border-l border-border pl-3">
              {a.steps.map((s, i) => (
                <li key={i} className="break-words">
                  {s.type === "search" ? t("nb.chat.stepSearch", { q: s.query ?? "", hits: s.hits ?? 0 }) : t("nb.chat.stepAnswer")}
                </li>
              ))}
            </ol>
          </details>
        )}
        <span className="tabular-nums">{t("nb.chat.timing", { s: (a.ms.total / 1000).toFixed(1) })}</span>
      </div>
    </div>
  );
}

export function ChatColumn({
  nb,
  canChat,
  maximized,
  onToggleMaximize,
  onOpenNote,
  className,
}: {
  nb: NotebookDetail;
  canChat: boolean;
  maximized: boolean;
  onToggleMaximize: () => void;
  onOpenNote: (n: Note) => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const errText = useErrorText();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [lang, setLang] = useState<Lang>("auto");
  const [mode, setMode] = useState<Mode>("auto");
  const nextId = useRef(1);
  const listRef = useRef<HTMLDivElement>(null);
  const busy = msgs.some((m) => m.pending);

  const enabled = nb.sources.filter((s) => s.enabled).length;
  const usable = nb.sources.some((s) => s.enabled && isReady(s)) || nb.notes.length > 0;
  const processing = nb.sources.some((s) => s.enabled && s.stage !== "done" && s.stage !== "failed");
  const disabled = !canChat || !usable;

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs.length, busy]);

  const history = () =>
    msgs
      .filter((m) => !m.pending && !m.error)
      .map((m) => ({
        role: m.role,
        content: m.role === "user" ? m.content : m.answer?.handoff ? "(handed off to support)" : (m.answer?.answer ?? ""),
      }));

  const send = async () => {
    const q = input.trim();
    if (!q || busy || disabled) return;
    const h = history();
    const uid = nextId.current++;
    const aid = nextId.current++;
    setInput("");
    setMsgs((s) => [...s, { id: uid, role: "user", content: q }, { id: aid, role: "assistant", content: "", pending: true }]);
    try {
      const answer = await api.post<ChatAnswer>(`/notebooks/${nb.id}/chat`, { q, history: h, mode, lang });
      setMsgs((s) => s.map((m) => (m.id === aid ? { ...m, pending: false, answer } : m)));
    } catch (e) {
      setMsgs((s) => s.map((m) => (m.id === aid ? { ...m, pending: false, error: errText(e) } : m)));
    }
  };

  const open = (c: ChatCitation) => {
    if (c.kind === "note") {
      const n = nb.notes.find((x) => x.title === c.doc_name) ?? nb.notes.find((x) => x.id === c.doc_id);
      if (n) onOpenNote(n);
      return;
    }
    if (c.doc_id) nav(`/notebooks/${nb.id}/sources/${c.doc_id}${c.page_from ? `?page=${c.page_from}` : ""}`);
  };

  return (
    <Column
      title={t("nb.chat.title")}
      className={className}
      bodyRef={listRef}
      actions={
        <>
          <UsagePill on={enabled} total={nb.sources.length} className="hidden xl:inline-flex" />
          <Select
            className="h-8 w-auto min-w-24 text-xs"
            aria-label={t("nb.chat.langLabel")}
            value={lang}
            onValueChange={(v) => setLang(v as Lang)}
            options={(["auto", "ja", "en", "vi"] as const).map((v) => ({ value: v, label: t(`nb.chat.lang.${v}`) }))}
          />
          <Select
            className="h-8 w-auto min-w-24 text-xs"
            aria-label={t("nb.chat.modeLabel")}
            value={mode}
            onValueChange={(v) => setMode(v as Mode)}
            options={(["auto", "deep"] as const).map((v) => ({ value: v, label: t(`nb.chat.mode.${v}`) }))}
          />
          <Tip content={t("nb.chat.clear")}>
            <Button
              variant="ghost"
              size="iconSm"
              disabled={!msgs.length || busy}
              onClick={() => setMsgs([])}
              aria-label={t("nb.chat.clear")}
            >
              <Eraser />
            </Button>
          </Tip>
          <Tip content={maximized ? t("nb.chat.restore") : t("nb.chat.maximize")}>
            <Button
              variant="ghost"
              size="iconSm"
              onClick={onToggleMaximize}
              aria-label={maximized ? t("nb.chat.restore") : t("nb.chat.maximize")}
              aria-pressed={maximized}
              className="hidden lg:inline-flex"
            >
              {maximized ? <Minimize2 /> : <Maximize2 />}
            </Button>
          </Tip>
        </>
      }
      footer={
        <div className="shrink-0 border-t border-border bg-card">
          {disabled && (
            <p className="flex items-start gap-1.5 border-b border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
              {canChat && processing && <Loader2 className="mt-px size-3.5 shrink-0 animate-spin" aria-hidden />}
              {!canChat ? t("nb.sources.readOnly") : processing ? t("nb.chat.disabledProcessing") : t("nb.chat.disabled")}
            </p>
          )}
          <form
            className={cn("flex items-end gap-2 p-3", maximized && "mx-auto w-full max-w-3xl")}
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <Textarea
              rows={2}
              value={input}
              maxLength={2000}
              disabled={disabled}
              placeholder={t("nb.chat.placeholder")}
              aria-label={t("nb.chat.placeholder")}
              className="min-h-[2.75rem] flex-1 resize-none disabled:opacity-60"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <Button type="submit" size="icon" disabled={!input.trim() || busy || disabled} aria-label={t("nb.chat.send")}>
              <SendHorizontal />
            </Button>
          </form>
          <p className={cn("px-3 pb-2 text-[11px] text-muted-foreground", maximized && "mx-auto w-full max-w-3xl")}>
            {t("nb.chat.notSaved")}
          </p>
        </div>
      }
    >
      <div className="h-full">
        {msgs.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 py-12 text-center">
            <div className="rounded-2xl bg-primary-soft p-3 text-primary">
              <MessageSquareText className="size-6" aria-hidden />
            </div>
            <div>
              <p className="font-medium">{t("nb.chat.emptyTitle")}</p>
              <p className="mt-1 text-sm text-muted-foreground">{t("nb.chat.emptyHint")}</p>
            </div>
          </div>
        ) : (
          <ol className={cn("flex flex-col gap-4 p-4", maximized && "mx-auto max-w-3xl")}>
            {msgs.map((m) =>
              m.role === "user" ? (
                <li key={m.id} className="flex justify-end gap-2">
                  <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-primary px-3.5 py-2 text-sm text-primary-foreground">
                    <p className="whitespace-pre-wrap break-words">{m.content}</p>
                  </div>
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
                    <User className="size-4" aria-hidden />
                  </span>
                </li>
              ) : (
                <li key={m.id} className="flex gap-2">
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary-soft text-primary">
                    <Bot className="size-4" aria-hidden />
                  </span>
                  <div className="min-w-0 max-w-[90%] rounded-2xl rounded-tl-sm border border-border bg-muted/40 px-3.5 py-2.5">
                    {m.pending && (
                      <span className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="size-4 animate-spin" aria-hidden />
                        {t("nb.chat.thinking")}
                      </span>
                    )}
                    {m.error && <p className="text-sm text-danger">{m.error}</p>}
                    {m.answer && <AnswerBlock a={m.answer} onOpen={open} />}
                  </div>
                </li>
              ),
            )}
          </ol>
        )}
      </div>
    </Column>
  );
}
