import { useQuery } from "@tanstack/react-query";
import { CornerDownLeft, Eraser, Headset, Loader2, Repeat, SendHorizontal } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Markdown, useErrorText } from "@/components/common";
import { Button, Select } from "@/components/ui";
import { api } from "@/lib/api";
import type { SearchHit } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ChatResult {
  answer: string;
  cited: number[];
  handoff: boolean;
  reason: "" | "no_source" | "not_in_sources";
  sources: SearchHit[];
  ms: { search: number; llm: number };
  usage: Record<string, number>;
  config_version: number;
}

interface Msg {
  id: number;
  role: "user" | "assistant";
  content: string; // câu hỏi, hoặc câu hỏi gốc của câu trả lời (dùng khi hỏi lại)
  result?: ChatResult;
  error?: string;
  pending?: boolean;
  history?: { role: "user" | "assistant"; content: string }[]; // ngữ cảnh lúc hỏi (để hỏi lại 3 lần y như cũ)
  stability?: { runs: (ChatResult | { error: string })[]; pending: boolean };
}

const EXAMPLES = ["CAD/CAM冠用材料(Ⅲ)の算定要件は？", "乳歯冠の点数は？", "M015-2 は何点ですか？"];

/** Câu trả lời có [n] → chip bấm được để xem nguồn n ở khung bên phải. */
function AnswerText({ text, onCite }: { text: string; onCite: (n: number) => void }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
      {parts.map((p, i) => {
        const m = /^\[(\d+)\]$/.exec(p);
        return m ? (
          <button
            key={i}
            type="button"
            onClick={() => onCite(Number(m[1]))}
            className="mx-0.5 inline-flex min-w-5 cursor-pointer items-center justify-center rounded border border-primary/30 px-1 align-baseline text-xs font-medium tabular-nums text-primary hover:bg-primary-soft"
          >
            {m[1]}
          </button>
        ) : (
          <span key={i}>{p}</span>
        );
      })}
    </p>
  );
}

/** Ổn định khi 3 lần hỏi cùng chuyển CSKH hoặc cùng trích các mã mục giống nhau. */
function stabilityVerdict(runs: (ChatResult | { error: string })[]) {
  const ok = runs.filter((r): r is ChatResult => "answer" in r);
  if (ok.length < runs.length) return "error";
  const sig = (r: ChatResult) =>
    r.handoff ? "handoff" : [...new Set(r.cited.map((n) => r.sources[n - 1]?.item_code || `#${n}`))].sort().join(",");
  return new Set(ok.map(sig)).size === 1 ? "stable" : "unstable";
}

export default function ChatTestPage() {
  const { t } = useTranslation();
  const errText = useErrorText();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [k, setK] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [focusSource, setFocusSource] = useState<number | null>(null);
  const nextId = useRef(1);
  const listRef = useRef<HTMLDivElement>(null);
  const status = useQuery({
    queryKey: ["search-status"],
    queryFn: () => api.get<{ configured: boolean; count: number }>("/search/status"),
  });
  const busy = msgs.some((m) => m.pending);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs.length, busy]);

  const call = (q: string, history: Msg["history"]) =>
    api.post<ChatResult>("/chat/test", { q, history, ...(k ? { k: Number(k) } : {}) });

  /** Ngữ cảnh gửi kèm: các lượt trước (câu bot đã chuyển CSKH gửi dạng ghi chú ngắn). */
  const historyOf = (list: Msg[]) =>
    list
      .filter((m) => !m.pending && !m.error)
      .map((m) =>
        m.role === "user"
          ? { role: "user" as const, content: m.content }
          : { role: "assistant" as const, content: m.result?.handoff ? "(handed off to support)" : (m.result?.answer ?? "") },
      );

  const send = async (text = input) => {
    const q = text.trim();
    if (!q || busy) return;
    const history = historyOf(msgs);
    const uid = nextId.current++;
    const aid = nextId.current++;
    setInput("");
    setMsgs((s) => [...s, { id: uid, role: "user", content: q }, { id: aid, role: "assistant", content: q, pending: true, history }]);
    try {
      const result = await call(q, history);
      setMsgs((s) => s.map((m) => (m.id === aid ? { ...m, pending: false, result } : m)));
      setSelected(aid);
      setFocusSource(null);
    } catch (e) {
      setMsgs((s) => s.map((m) => (m.id === aid ? { ...m, pending: false, error: errText(e) } : m)));
    }
  };

  /** Hỏi lại 3 lần cùng câu hỏi + cùng ngữ cảnh để xem câu trả lời có ổn định không. */
  const checkStability = async (m: Msg) => {
    setSelected(m.id);
    setMsgs((s) => s.map((x) => (x.id === m.id ? { ...x, stability: { runs: [], pending: true } } : x)));
    const runs = await Promise.all(
      [0, 1, 2].map(() => call(m.content, m.history).catch((e: unknown) => ({ error: errText(e) }))),
    );
    setMsgs((s) => s.map((x) => (x.id === m.id ? { ...x, stability: { runs, pending: false } } : x)));
  };

  const cite = (m: Msg, n: number) => {
    setSelected(m.id);
    setFocusSource(n);
    window.setTimeout(() => document.getElementById(`src-${m.id}-${n}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 50);
  };

  const sel = useMemo(() => msgs.find((m) => m.id === selected && m.result), [msgs, selected]);

  return (
    <div className="flex h-full min-h-[32rem] flex-col">
      {/* thanh trên của màn (màn chia ngăn: không dùng PageHeader) */}
      <header className="flex min-h-12 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-card px-4 py-2">
        <h1 className="text-base font-semibold">{t("chat.title")}</h1>
        {status.data && (
          <span className={cn("text-xs", status.data.configured ? "text-muted-foreground" : "text-warning")}>
            {status.data.configured ? t("search.indexed", { n: status.data.count }) : t("common.notConfigured")}
          </span>
        )}
        <span className="flex-1" />
        <Select
          className="h-8 w-36 text-xs shadow-none"
          aria-label={t("search.topK")}
          value={k || "default"}
          onValueChange={(v) => setK(v === "default" ? "" : v)}
          options={[
            { value: "default", label: `${t("search.topK")}: ${t("chat.defaultK")}` },
            ...["3", "5", "10"].map((v) => ({ value: v, label: `${t("search.topK")}: ${v}` })),
          ]}
        />
        <Button
          variant="ghost"
          size="sm"
          disabled={!msgs.length || busy}
          onClick={() => {
            setMsgs([]);
            setSelected(null);
          }}
        >
          <Eraser />
          {t("chat.clear")}
        </Button>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_26rem]">
        {/* Hội thoại */}
        <section className="flex min-h-[28rem] min-w-0 flex-col lg:min-h-0">
          <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto" aria-live="polite">
            <div className="mx-auto flex max-w-2xl flex-col gap-6 px-6 py-6">
              {msgs.length === 0 && (
                <div className="py-6">
                  <h2 className="text-base font-semibold">{t("chat.emptyTitle")}</h2>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{t("chat.subtitle")}</p>
                  <p className="mb-2 mt-6 text-xs text-muted-foreground">{t("chat.examples")}</p>
                  <ul className="overflow-hidden rounded-lg border border-border">
                    {EXAMPLES.map((ex) => (
                      <li key={ex} className="border-b border-border last:border-b-0">
                        <button
                          type="button"
                          onClick={() => send(ex)}
                          className="flex w-full cursor-pointer items-center justify-between gap-3 bg-card px-4 py-2.5 text-left text-sm hover:bg-accent"
                        >
                          {ex}
                          <SendHorizontal className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {msgs.map((m) =>
                m.role === "user" ? (
                  <div key={m.id} className="flex justify-end">
                    <p className="max-w-[80%] whitespace-pre-wrap break-words rounded-lg bg-muted px-3.5 py-2 text-sm">{m.content}</p>
                  </div>
                ) : (
                  <article
                    key={m.id}
                    className={cn(
                      "flex flex-col gap-2 border-l-2 pl-4 transition-colors",
                      m.id === selected && m.result ? "border-primary" : "border-transparent",
                    )}
                  >
                    {m.pending && (
                      <span className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="size-4 animate-spin" />
                        {t("chat.thinking")}
                      </span>
                    )}
                    {m.error && <p className="text-sm text-danger">{m.error}</p>}
                    {m.result && m.result.handoff && (
                      <div className="text-sm">
                        <p className="flex items-center gap-2 font-medium text-warning">
                          <Headset className="size-4 shrink-0" aria-hidden />
                          {t("chat.handoff")}
                        </p>
                        <p className="mt-0.5 text-muted-foreground">{t(`chat.reasons.${m.result.reason || "not_in_sources"}`)}</p>
                      </div>
                    )}
                    {m.result && !m.result.handoff && <AnswerText text={m.result.answer} onCite={(n) => cite(m, n)} />}
                    {m.result && (
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                        <span className="tabular-nums">{t("chat.timing", m.result.ms)}</span>
                        <button type="button" className="cursor-pointer hover:text-foreground" onClick={() => setSelected(m.id)}>
                          {t("chat.sourcesCount", { n: m.result.sources.length, cited: m.result.cited.length })}
                        </button>
                        <button
                          type="button"
                          className="inline-flex cursor-pointer items-center gap-1 hover:text-foreground disabled:opacity-50"
                          disabled={m.stability?.pending}
                          onClick={() => checkStability(m)}
                        >
                          <Repeat className="size-3" />
                          {t("chat.stabilityRun")}
                        </button>
                      </div>
                    )}
                  </article>
                ),
              )}
            </div>
          </div>
          <form
            className="shrink-0 px-4 pb-3 pt-2"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            {/* Ô nhập kiểu chatbox: nút gửi (↵) nằm trong khung, góc phải */}
            <div className="mx-auto flex max-w-2xl items-end gap-1 rounded-lg border border-input bg-background py-1 pl-3 pr-1 transition-[color,box-shadow] focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50">
              <textarea
                rows={1}
                value={input}
                maxLength={1000}
                placeholder={t("chat.placeholder")}
                aria-label={t("chat.placeholder")}
                className="field-sizing-content max-h-40 min-h-9 flex-1 resize-none bg-transparent py-2 text-sm outline-none placeholder:text-muted-foreground"
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    send();
                  }
                }}
              />
              <Button
                type="submit"
                variant="ghost"
                size="icon"
                className="size-9 shrink-0 text-muted-foreground hover:text-foreground"
                disabled={!input.trim() || busy}
                aria-label={t("chat.send")}
                title={t("chat.send")}
              >
                <CornerDownLeft />
              </Button>
            </div>
            <p className="mx-auto mt-1.5 max-w-2xl text-xs text-muted-foreground">{t("chat.notSaved")}</p>
          </form>
        </section>

        {/* Căn cứ của câu trả lời đang chọn */}
        <aside className="flex min-h-[20rem] min-w-0 flex-col border-t border-border bg-card lg:min-h-0 lg:border-l lg:border-t-0">
          <div className="shrink-0 border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">{t("chat.sources")}</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">{sel ? t("chat.sourcesHint") : t("chat.selectHint")}</p>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {sel?.stability && (
              <section className="border-b border-border px-4 py-3">
                <div className="mb-2 flex items-center justify-between gap-2 text-xs">
                  <h3 className="font-semibold">{t("chat.stability")}</h3>
                  {sel.stability.pending ? (
                    <Loader2 className="size-4 animate-spin text-muted-foreground" />
                  ) : (
                    (() => {
                      const v = stabilityVerdict(sel.stability.runs);
                      return (
                        <span
                          className={cn(
                            "font-medium",
                            v === "stable" ? "text-success" : v === "unstable" ? "text-warning" : "text-danger",
                          )}
                        >
                          {t(`chat.verdict.${v}`)}
                        </span>
                      );
                    })()
                  )}
                </div>
                <ol className="flex flex-col gap-2 text-xs">
                  {sel.stability.runs.map((r, i) => (
                    <li key={i} className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-1">
                      <span className="tabular-nums text-muted-foreground">#{i + 1}</span>
                      {"error" in r ? (
                        <span className="text-danger">{r.error}</span>
                      ) : r.handoff ? (
                        <span className="text-warning">{t("chat.handoff")}</span>
                      ) : (
                        <span className="min-w-0">
                          <span className="font-mono font-semibold">
                            {[...new Set(r.cited.map((n) => r.sources[n - 1]?.item_code).filter(Boolean))].join(", ") || "—"}
                          </span>
                          <span className="line-clamp-2 text-muted-foreground">{r.answer}</span>
                        </span>
                      )}
                    </li>
                  ))}
                </ol>
              </section>
            )}
            {sel?.result && sel.result.sources.length === 0 && (
              <p className="px-4 py-6 text-center text-sm text-muted-foreground">{t("chat.noSources")}</p>
            )}
            <ol>
              {sel?.result?.sources.map((h, i) => {
                const n = i + 1;
                const cited = sel.result!.cited.includes(n);
                return (
                  <li
                    key={h.id}
                    id={`src-${sel.id}-${n}`}
                    className={cn(
                      "border-b border-border px-4 py-3 transition-colors",
                      focusSource === n && "bg-primary-soft/40",
                      !cited && "text-muted-foreground",
                    )}
                  >
                    <div className="flex items-baseline gap-2 text-xs">
                      <span className="w-4 shrink-0 font-semibold tabular-nums">{n}</span>
                      {h.item_code && <span className="font-mono font-semibold text-foreground">{h.item_code}</span>}
                      {cited && <span className="font-medium text-primary">{t("chat.cited")}</span>}
                      <span className="ml-auto font-mono tabular-nums text-muted-foreground">{h.score.toFixed(3)}</span>
                    </div>
                    <Link
                      to={`/documents/${h.doc_id}`}
                      className="mt-0.5 block pl-6 text-xs text-muted-foreground hover:text-primary hover:underline"
                    >
                      {h.doc_name} · P{h.page_from}
                      {h.page_to !== h.page_from ? `–${h.page_to}` : ""}
                    </Link>
                    <div className="ml-6 mt-2 max-h-40 overflow-auto rounded-md bg-muted/50 px-3 py-2">
                      <Markdown text={h.content} className="prose-compact" />
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>
        </aside>
      </div>
    </div>
  );
}
