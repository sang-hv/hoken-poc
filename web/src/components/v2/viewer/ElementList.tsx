import { MousePointerClick, Shapes } from "lucide-react";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { EmptyState } from "@/components/ui";
import type { Element } from "@/lib/v2types";
import { cn } from "@/lib/utils";
import { OrderBadge, StatusChip, WeakChip } from "./shared";

export type ElementFilter = "all" | "weak" | "fixed";
export const FILTERS: ElementFilter[] = ["all", "weak", "fixed"];

export function matchFilter(el: Element, f: ElementFilter) {
  if (f === "weak") return el.status === "weak";
  if (f === "fixed") return el.status === "fixed" || el.status === "accepted";
  return true;
}

function Row({
  el,
  hovered,
  onHover,
  onSelect,
}: {
  el: Element;
  hovered: boolean;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLButtonElement>(null);
  // Hover khung trên ảnh → đưa dòng tương ứng vào tầm nhìn (không cuộn khi chính dòng đang được hover).
  useEffect(() => {
    if (hovered && !ref.current?.matches(":hover")) ref.current?.scrollIntoView({ block: "nearest" });
  }, [hovered]);
  const noText = !el.text.trim();
  return (
    <li>
      <button
        ref={ref}
        type="button"
        onMouseEnter={() => onHover(el.id)}
        onMouseLeave={() => onHover(null)}
        onFocus={() => onHover(el.id)}
        onBlur={() => onHover(null)}
        onClick={() => onSelect(el.id)}
        className={cn(
          "flex w-full cursor-pointer gap-2.5 rounded-lg border px-3 py-2.5 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-ring",
          hovered ? "border-primary/40 bg-accent" : "border-transparent hover:bg-accent",
          el.status === "weak" && !hovered && "border-danger/20 bg-danger-soft/40",
        )}
      >
        <OrderBadge label={el.label} order={el.order} className="mt-0.5" />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-semibold">{t(`viewer.label.${el.label}`, { defaultValue: el.label })}</span>
            {el.status === "weak"
              ? el.weak.map((w, i) => <WeakChip key={i} code={w.code} severity={w.severity} />)
              : el.status !== "ok" && <StatusChip status={el.status} />}
          </span>
          <span
            className={cn(
              "mt-1 line-clamp-3 whitespace-pre-line break-words text-[13px] leading-relaxed",
              noText ? "italic text-muted-foreground" : "text-foreground/90",
            )}
          >
            {noText ? (el.label === "picture" ? t("viewer.elements.noDesc") : t("viewer.detail.emptyText")) : el.text}
          </span>
        </span>
      </button>
    </li>
  );
}

/** Danh sách phần tử của trang theo thứ tự đọc, có bộ lọc すべて / 弱点 / 修正済み. */
export function ElementList({
  elements,
  filter,
  onFilter,
  hovered,
  onHover,
  onSelect,
}: {
  elements: Element[];
  filter: ElementFilter;
  onFilter: (f: ElementFilter) => void;
  hovered: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const counts: Record<ElementFilter, number> = {
    all: elements.length,
    weak: elements.filter((e) => matchFilter(e, "weak")).length,
    fixed: elements.filter((e) => matchFilter(e, "fixed")).length,
  };
  const list = elements.filter((e) => matchFilter(e, filter)).sort((a, b) => a.order - b.order);
  const label: Record<ElementFilter, string> = {
    all: t("viewer.elements.filterAll"),
    weak: t("viewer.elements.filterWeak"),
    fixed: t("viewer.elements.filterFixed"),
  };
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 space-y-2.5 border-b border-border px-4 py-3">
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <MousePointerClick className="size-3.5 shrink-0" aria-hidden />
          {t("viewer.elements.hint")}
        </p>
        <div role="radiogroup" aria-label={t("viewer.elements.filterLabel")} className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              role="radio"
              aria-checked={filter === f}
              onClick={() => onFilter(f)}
              className={cn(
                "inline-flex cursor-pointer items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium transition",
                filter === f
                  ? "border-primary bg-primary-soft text-primary"
                  : "border-border text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
            >
              {label[f]}
              <span className={cn("tabular-nums", f === "weak" && counts.weak > 0 && filter !== f && "text-danger")}>{counts[f]}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {list.length === 0 ? (
          <EmptyState icon={<Shapes />} title={elements.length ? t("viewer.elements.emptyFilter") : t("viewer.elements.empty")} />
        ) : (
          <ul className="space-y-1">
            {list.map((el) => (
              <Row key={el.id} el={el} hovered={hovered === el.id} onHover={onHover} onSelect={onSelect} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
