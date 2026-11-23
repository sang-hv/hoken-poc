import { AlertCircle, AlertTriangle, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { JobEvent } from "@/lib/types";
import { cn, fmtTime } from "@/lib/utils";
import { Switch } from "./ui";

export function useEventText() {
  const { t } = useTranslation();
  return (e: JobEvent) => {
    const p: Record<string, unknown> = { ...e.params };
    if (e.code === "route.decided" && typeof p.route === "string") p.route = t(`route.${p.route}`);
    if (typeof p.low_grade === "string") p.low_grade = t(`grades.${p.low_grade}`, { defaultValue: p.low_grade });
    if (e.code === "job.blocked" && typeof p.reason === "string")
      p.reason = t(`errors.${p.reason}`, { defaultValue: p.reason });
    let text = t(`events.${e.code}`, { ...p, defaultValue: e.code });
    if (e.code === "route.decided" && Array.isArray(e.params.reasons) && e.params.reasons.length) {
      text += " — " + (e.params.reasons as string[]).map((r) => t(`reasons.${r}`, { defaultValue: r })).join(", ");
    }
    return text;
  };
}

/** Chỉ warn / error có icon — dòng info chiếm đa số, icon lặp lại ở mọi dòng không mang thông tin. */
const LEVEL_ICON: Partial<Record<JobEvent["level"], React.ReactNode>> = {
  warn: <AlertTriangle className="size-3.5 text-warning" />,
  error: <AlertCircle className="size-3.5 text-danger" />,
};

export function LiveLog({
  events,
  connected,
  className,
  showStep = true,
  height = "h-80",
  max,
  bare = false,
  open,
  onOpenChange,
}: {
  events: JobEvent[];
  connected?: boolean;
  className?: string;
  showStep?: boolean;
  height?: string;
  /** số dòng tối đa đang giữ — đạt mức này thì báo chỉ hiện các dòng mới nhất */
  max?: number;
  /** nằm trong ngăn (không viền / bo góc riêng) */
  bare?: boolean;
  /** có → thu gọn được bằng thanh tiêu đề */
  open?: boolean;
  onOpenChange?: (o: boolean) => void;
}) {
  const { t } = useTranslation();
  const text = useEventText();
  const box = useRef<HTMLDivElement>(null);
  const [follow, setFollow] = useState(true);
  const collapsible = open !== undefined && !!onOpenChange;
  const shown = !collapsible || open;

  useEffect(() => {
    if (shown && follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [events, follow, shown]);

  const title = (
    <>
      <span
        className={cn("size-1.5 rounded-full", connected ? "bg-success animate-pulse-dot" : "bg-muted-foreground/50")}
        aria-hidden
      />
      <span className="font-medium">{t("jobs.log")}</span>
      <span className="text-xs tabular-nums text-muted-foreground">
        {connected !== undefined && (connected ? t("common.live") : t("common.offline"))}
        {events.length > 0 && ` · ${t("viewer.pipeline.logCount", { n: events.length })}`}
        {max !== undefined && events.length >= max && ` · ${t("jobs.latestOnly", { n: max })}`}
      </span>
    </>
  );

  return (
    <div className={cn("flex flex-col overflow-hidden bg-card", !bare && "rounded-lg border border-border", className)}>
      <div className={cn("flex h-10 shrink-0 items-center justify-between gap-3 px-4", shown && "border-b border-border")}>
        {collapsible ? (
          <button
            type="button"
            onClick={() => onOpenChange(!open)}
            aria-expanded={open}
            className="-ml-1 flex min-w-0 cursor-pointer items-center gap-2 rounded px-1 text-sm hover:text-foreground"
          >
            <ChevronRight className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-90")} aria-hidden />
            {title}
          </button>
        ) : (
          <div className="flex min-w-0 items-center gap-2 text-sm">{title}</div>
        )}
        {shown && (
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            {t("jobs.autoScroll")}
            <Switch checked={follow} onCheckedChange={setFollow} />
          </label>
        )}
      </div>
      {shown && (
        <div ref={box} className={cn("overflow-y-auto font-mono text-xs leading-relaxed", height)}>
          {events.length === 0 ? (
            <p className="p-4 font-sans text-sm text-muted-foreground">{t("common.empty")}</p>
          ) : (
            <ul className="py-1">
              {events.map((e) => (
                <li
                  key={e.id}
                  className={cn(
                    "grid grid-cols-[4.5rem_1rem_minmax(0,1fr)] items-start gap-2 px-4 py-1",
                    e.level === "error" && "bg-danger-soft/50",
                    e.level === "warn" && "bg-warning-soft/40",
                  )}
                >
                  <span className="pt-px text-muted-foreground tabular-nums">{fmtTime(e.ts)}</span>
                  <span className="pt-0.5">{LEVEL_ICON[e.level]}</span>
                  <span className="min-w-0 break-words font-sans text-dense">
                    {showStep && e.step && (
                      <span className="mr-2 text-muted-foreground">
                        {t(`steps.${e.step}`, { defaultValue: e.step })}
                        {e.page ? ` · p${e.page}` : ""}
                      </span>
                    )}
                    {text(e)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
