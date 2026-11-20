import { AlertCircle, AlertTriangle, Info, Radio } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { JobEvent } from "@/lib/types";
import { cn, fmtTime } from "@/lib/utils";
import { Badge, Switch } from "./ui";

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

const LEVEL_ICON = {
  debug: <Info className="size-3.5 text-muted-foreground" />,
  info: <Info className="size-3.5 text-info" />,
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
}: {
  events: JobEvent[];
  connected?: boolean;
  className?: string;
  showStep?: boolean;
  height?: string;
  /** số dòng tối đa đang giữ — đạt mức này thì báo chỉ hiện các dòng mới nhất */
  max?: number;
}) {
  const { t } = useTranslation();
  const text = useEventText();
  const box = useRef<HTMLDivElement>(null);
  const [follow, setFollow] = useState(true);

  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [events, follow]);

  return (
    <div className={cn("flex flex-col overflow-hidden rounded-xl border border-border bg-card", className)}>
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Radio className={cn("size-4", connected ? "text-success animate-pulse-dot" : "text-muted-foreground")} />
          {t("jobs.log")}
          {connected !== undefined && (
            <Badge tone={connected ? "success" : "neutral"}>{connected ? t("common.live") : t("common.offline")}</Badge>
          )}
          {max !== undefined && events.length >= max && (
            <span className="text-xs font-normal text-muted-foreground">{t("jobs.latestOnly", { n: max })}</span>
          )}
        </div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          {t("jobs.autoScroll")}
          <Switch checked={follow} onCheckedChange={setFollow} />
        </label>
      </div>
      <div ref={box} className={cn("overflow-y-auto font-mono text-[12px] leading-relaxed", height)}>
        {events.length === 0 ? (
          <p className="p-4 text-muted-foreground">{t("common.empty")}</p>
        ) : (
          <ul className="divide-y divide-border/60">
            {events.map((e) => (
              <li
                key={e.id}
                className={cn(
                  "flex items-start gap-2 px-4 py-1.5",
                  e.level === "error" && "bg-danger-soft/50",
                  e.level === "warn" && "bg-warning-soft/40",
                )}
              >
                <span className="shrink-0 pt-0.5 text-muted-foreground tabular-nums">{fmtTime(e.ts)}</span>
                <span className="shrink-0 pt-0.5">{LEVEL_ICON[e.level]}</span>
                {showStep && e.step && (
                  <span className="shrink-0 rounded bg-muted px-1.5 text-[11px] text-muted-foreground">
                    {t(`steps.${e.step}`, { defaultValue: e.step })}
                    {e.page ? ` · p${e.page}` : ""}
                  </span>
                )}
                <span className="min-w-0 break-words font-sans text-[13px]">{text(e)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
