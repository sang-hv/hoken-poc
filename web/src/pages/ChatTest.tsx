import { useQuery } from "@tanstack/react-query";
import { Bot, Database, Eraser, Headset, Loader2, Repeat, SendHorizontal, User } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Markdown, PageHeader, useErrorText } from "@/components/common";
import { Badge, Button, Card, Select, Textarea } from "@/components/ui";
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
            className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-primary-soft px-1 align-text-top text-[11px] font-semibold text-primary hover:brightness-95"
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
    <div className="flex flex-col lg:h-[calc(100dvh-3.5rem-3rem)]">
      <PageHeader
        title={t("chat.title")}
        subtitle={t("chat.subtitle")}
        actions={
          <>
            {status.data && (
              <Badge tone={status.data.configured ? "primary" : "warning"}>
                <Database />
                {status.data.configured ? t("search.indexed", { n: status.data.count }) : t("common.notConfigured")}
              </Badge>
            )}
            <Select
              className="h-8 w-36 text-xs"
              aria-label={t("search.topK")}
              value={k || "default"}
              onValueChange={(v) => setK(v === "default" ? "" : v)}
              options={[
                { value: "default", label: `${t("search.topK")}: ${t("chat.defaultK")}` },
                ...["3", "5", "10"].map((v) => ({ value: v, label: `${t("search.topK")}: ${v}` })),
              ]}
            />
            <Button
              variant="outline"
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
          </>
        }
      />
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        {/* Hội thoại */}
        <Card className="flex min-h-[28rem] flex-col overflow-hidden">
          <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto p-4" aria-live="polite">
            {msgs.length === 0 && (
              <div className="flex h-full flex-col items-center justify-center gap-4 py-10 text-center">
                <div className="rounded-2xl bg-primary-soft p-3 text-primary">
                  <Bot className="size-6" />
                </div>
                <div>
                  <p className="font-medium">{t("chat.emptyTitle")}</p>
                  <p className="mt-1 text-sm text-muted-foreground">{t("chat.emptyHint")}</p>
                </div>
                <div className="flex flex-wrap justify-center gap-2">
                  {EXAMPLES.map((ex) => (
                    <Button key={ex} variant="secondary" size="sm" onClick={() => send(ex)}>
                      {ex}
                    </Button>
                  ))}
                </div>
              </div>
            )}
            <ol className="flex flex-col gap-4">
              {msgs.map((m) =>
                m.role === "user" ? (
                  <li key={m.id} className="flex justify-end gap-2">
                    <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-primary px-3.5 py-2 text-sm text-primary-foreground">
                      <p className="whitespace-pre-wrap break-words">{m.content}</p>
                    </div>
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
                      <User className="size-4" />
                    </span>
                  </li>
                ) : (
                  <li key={m.id} className="flex gap-2">
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary-soft text-primary">
                      <Bot className="size-4" />
                    </span>
                    <div
                      className={cn(
                        "flex max-w-[85%] flex-col gap-2 rounded-2xl rounded-tl-sm border px-3.5 py-2.5",
                        m.id === selected ? "border-primary/50 bg-card" : "border-border bg-muted/40",
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
                        <div className="flex items-start gap-2 rounded-lg bg-warning-soft/70 px-3 py-2 text-sm">
                          <Headset className="mt-0.5 size-4 shrink-0 text-warning" />
                          <span>
                            <span className="font-medium">{t("chat.handoff")}</span>
                            <span className="block text-xs text-muted-foreground">
                              {t(`chat.reasons.${m.result.reason || "not_in_sources"}`)}
                            </span>
                          </span>
                        </div>
                      )}
                      {m.result && !m.result.handoff && <AnswerText text={m.result.answer} onCite={(n) => cite(m, n)} />}
                      {m.result && (
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                          <span className="tabular-nums">{t("chat.timing", m.result.ms)}</span>
                          <button type="button" className="hover:text-foreground" onClick={() => setSelected(m.id)}>
                            {t("chat.sourcesCount", { n: m.result.sources.length, cited: m.result.cited.length })}
                          </button>
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 hover:text-foreground disabled:opacity-50"
                            disabled={m.stability?.pending}
                            onClick={() => checkStability(m)}
                          >
                            <Repeat className="size-3" />
                            {t("chat.stabilityRun")}
                          </button>
                        </div>
                      )}
                    </div>
                  </li>
                ),
              )}
            </ol>
          </div>
          <form
            className="flex items-end gap-2 border-t border-border bg-card p-3"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <Textarea
              rows={2}
              value={input}
              maxLength={1000}
              placeholder={t("chat.placeholder")}
              aria-label={t("chat.placeholder")}
              className="min-h-[2.75rem] flex-1 resize-none"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <Button type="submit" disabled={!input.trim() || busy} aria-label={t("chat.send")}>
              <SendHorizontal />
              <span className="hidden sm:inline">{t("chat.send")}</span>
            </Button>
          </form>
          <p className="border-t border-border bg-card px-3 py-1.5 text-[11px] text-muted-foreground">{t("chat.notSaved")}</p>
        </Card>

        {/* Căn cứ của câu trả lời đang chọn */}
        <Card className="flex min-h-[20rem] flex-col overflow-hidden">
          <div className="border-b border-border px-4 py-3">
            <p className="text-sm font-semibold">{t("chat.sources")}</p>
            <p className="text-xs text-muted-foreground">{sel ? t("chat.sourcesHint") : t("chat.selectHint")}</p>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {sel?.stability && (
              <div className="mb-3 rounded-lg border border-border p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="text-xs font-semibold">{t("chat.stability")}</p>
                  {sel.stability.pending ? (
                    <Loader2 className="size-4 animate-spin text-muted-foreground" />
                  ) : (
                    (() => {
                      const v = stabilityVerdict(sel.stability.runs);
                      return <Badge tone={v === "stable" ? "success" : v === "unstable" ? "warning" : "danger"}>{t(`chat.verdict.${v}`)}</Badge>;
                    })()
                  )}
                </div>
                <ol className="flex flex-col gap-1.5 text-xs">
                  {sel.stability.runs.map((r, i) => (
                    <li key={i} className="rounded-md bg-muted/50 px-2 py-1.5">
                      <span className="mr-1.5 font-mono text-muted-foreground">#{i + 1}</span>
                      {"error" in r ? (
                        <span className="text-danger">{r.error}</span>
                      ) : r.handoff ? (
                        <span className="text-warning">{t("chat.handoff")}</span>
                      ) : (
                        <>
                          {[...new Set(r.cited.map((n) => r.sources[n - 1]?.item_code).filter(Boolean))].map((c) => (
                            <Badge key={c} tone="primary" className="mr-1 font-mono">
                              {c}
                            </Badge>
                          ))}
                          <span className="line-clamp-2 text-muted-foreground">{r.answer}</span>
                        </>
                      )}
                    </li>
                  ))}
                </ol>
              </div>
            )}
            {sel?.result && sel.result.sources.length === 0 && (
              <p className="px-1 py-6 text-center text-sm text-muted-foreground">{t("chat.noSources")}</p>
            )}
            <ol className="flex flex-col gap-2">
              {sel?.result?.sources.map((h, i) => {
                const n = i + 1;
                const cited = sel.result!.cited.includes(n);
                return (
                  <li
                    key={h.id}
                    id={`src-${sel.id}-${n}`}
                    className={cn(
                      "rounded-lg border p-3 transition",
                      cited ? "border-primary/50" : "border-border opacity-80",
                      focusSource === n && "ring-2 ring-primary/40",
                    )}
                  >
                    <div className="mb-2 flex flex-wrap items-center gap-1.5 text-xs">
                      <span className="flex size-5 items-center justify-center rounded-md bg-primary-soft font-semibold text-primary">{n}</span>
                      <Badge tone="primary" className="font-mono">
                        {h.item_code || "—"}
                      </Badge>
                      {cited && <Badge tone="success">{t("chat.cited")}</Badge>}
                      <span className="ml-auto font-mono text-muted-foreground">{h.score.toFixed(3)}</span>
                    </div>
                    <Link to={`/documents/${h.doc_id}`} className="text-xs font-medium hover:text-primary">
                      {h.doc_name} · P{h.page_from}
                      {h.page_to !== h.page_from ? `–${h.page_to}` : ""}
                    </Link>
                    <div className="mt-2 max-h-40 overflow-auto rounded-md bg-muted/50 p-2 text-xs">
                      <Markdown text={h.content} />
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>
        </Card>
      </div>
    </div>
  );
}
