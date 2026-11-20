import { ImageOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Element, PageElements } from "@/lib/v2types";
import { cn } from "@/lib/utils";
import { labelColor, pageImageUrl } from "./shared";

function worstSeverity(el: Element): "warn" | "error" | null {
  if (el.status !== "weak" || !el.weak.length) return el.status === "weak" ? "warn" : null;
  return el.weak.some((w) => w.severity === "error") ? "error" : "warn";
}

/** Ảnh trang + khung phần tử (màu theo loại, số thứ tự đọc ở góc trên-trái, điểm yếu viền nét đứt). */
export function PageCanvas({
  docId,
  page,
  data,
  zoom,
  hovered,
  selected,
  onHover,
  onSelect,
}: {
  docId: string;
  page: number;
  data?: PageElements;
  zoom: number;
  hovered: string | null;
  selected: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const selRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setLoaded(false);
    setFailed(false);
  }, [docId, page]);
  useEffect(() => {
    if (selected) selRef.current?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [selected, loaded]);

  const size = data?.image_size;
  const aspect = size && size[0] > 0 && size[1] > 0 ? `${size[0]} / ${size[1]}` : "1 / 1.414";

  return (
    <div className="relative mx-auto" style={{ width: `${zoom}%` }}>
      <div className="relative w-full rounded-md border border-border bg-white shadow-card">
        {!loaded && !failed && <div className="w-full animate-pulse rounded-md bg-muted" style={{ aspectRatio: aspect }} />}
        {failed ? (
          <div
            className="flex w-full flex-col items-center justify-center gap-2 rounded-md bg-muted text-sm text-muted-foreground"
            style={{ aspectRatio: aspect }}
          >
            <ImageOff className="size-6" aria-hidden />
            {t("viewer.page.imageError")}
          </div>
        ) : (
          <img
            key={`${docId}:${page}`}
            src={pageImageUrl(docId, page)}
            alt={t("viewer.page.alt", { page })}
            onLoad={() => setLoaded(true)}
            onError={() => setFailed(true)}
            className={cn("block w-full rounded-md", !loaded && "absolute inset-0 opacity-0")}
          />
        )}
        {loaded &&
          data?.elements.map((el) => {
            const c = labelColor(el.label);
            const sev = worstSeverity(el);
            const isHover = hovered === el.id;
            const isSel = selected === el.id;
            const [x0, y0, x1, y1] = el.bbox;
            return (
              <button
                key={el.id}
                ref={isSel ? selRef : undefined}
                type="button"
                aria-label={t("viewer.elements.open", { order: el.order, label: t(`viewer.label.${el.label}`, { defaultValue: el.label }) })}
                aria-pressed={isSel}
                onMouseEnter={() => onHover(el.id)}
                onMouseLeave={() => onHover(null)}
                onFocus={() => onHover(el.id)}
                onBlur={() => onHover(null)}
                onClick={() => onSelect(el.id)}
                className={cn(
                  "absolute cursor-pointer rounded-[3px] outline-none transition-colors",
                  sev ? "border-2 border-dashed" : "border-[1.5px]",
                  sev === "error" ? "border-danger" : sev === "warn" ? "border-warning" : c.border,
                  (isHover || isSel) && (sev === "error" ? "bg-danger/15" : sev === "warn" ? "bg-warning/20" : c.fill),
                  isSel && "z-10 ring-2 ring-ring ring-offset-1 ring-offset-white",
                  isHover && "z-10",
                )}
                style={{
                  left: `${x0 * 100}%`,
                  top: `${y0 * 100}%`,
                  width: `${Math.max(0.5, (x1 - x0) * 100)}%`,
                  height: `${Math.max(0.5, (y1 - y0) * 100)}%`,
                }}
              >
                <span
                  aria-hidden
                  className={cn(
                    "pointer-events-none absolute -left-2 -top-2 flex h-4 min-w-4 items-center justify-center rounded-[4px] px-0.5 text-[10px] font-semibold leading-none tabular-nums shadow-sm",
                    c.badge,
                    (isHover || isSel) && "scale-125",
                  )}
                >
                  {el.order}
                </span>
              </button>
            );
          })}
      </div>
    </div>
  );
}
