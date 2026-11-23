/** Hai ngăn 「認識結果」 và danh sách trang ở tab パイプライン (định nghĩa nhóm: docs/STATUS.md §C).
 *  - 認識結果: 良好 / 要確認 / 未認識 ở hai mốc 現在 | 機械読取時 đặt cạnh nhau. Bấm một dòng → ngăn phải lọc đúng các
 *    trang thuộc nhóm đó (dòng 計 → mọi trang); bấm lại → về 要対応ページ.
 *  - Ngăn phải mặc định là 要対応ページ: trang còn 未認識 / 要確認 / lỗi, nặng nhất lên đầu — tài liệu vài trăm trang vẫn
 *    chỉ hiện trang cần làm; ngăn này tự cuộn. Mỗi dòng mở trang đó ở tab 検査. */
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { RecognitionSummary } from "@/lib/v2types";
import { cn } from "@/lib/utils";
import { Pane, PaneCol, PaneHeader, PaneRow } from "./pane";
import { vk } from "./shared";

const pct = (n: number, d: number) => (d ? Math.round((100 * n) / d) : 0);
const SUM_COL = "w-24";
const PAGE_COL = "w-12 xl:w-16";
const TONE = { warning: "text-warning", danger: "text-danger" } as const;

type Filter = "todo" | "all" | "good" | "weak" | "unread";
const LIST_TITLE: Record<Filter, string> = {
  todo: "todo",
  all: "pagesAll",
  good: "pagesGood",
  weak: "pagesWeak",
  unread: "pagesUnread",
};
type PageItem = { page: number; book: number | null; weak: number; unread: number; failed: boolean };

/** "85%" + số phần tử nhỏ. Chỉ tô màu khi nhóm cần chú ý và khác 0. */
function Num({ n, of, tone }: { n: number; of: number; tone?: keyof typeof TONE }) {
  return (
    <PaneCol width={SUM_COL}>
      <span className={cn("font-medium", n > 0 && tone && TONE[tone])}>{pct(n, of)}%</span>
      <span className="ml-1.5 inline-block min-w-8 text-xs text-muted-foreground">{n}</span>
    </PaneCol>
  );
}

function Loading() {
  return (
    <div className="space-y-2 px-5 py-3">
      {Array.from({ length: 4 }, (_, i) => (
        <Skeleton key={i} className="h-5" />
      ))}
    </div>
  );
}

export function RecognitionPanes({ docId, className }: { docId: string; className?: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: vk.recognition(docId),
    queryFn: () => api.get<RecognitionSummary>(`/documents/${docId}/recognition`),
  });
  const r = q.data;
  const n = r?.elements ?? 0;
  const empty = !!r && n === 0 && r.pages_failed.length === 0;

  const [filter, setFilter] = useState<Filter>("todo");
  const pick = (f: Filter) => setFilter((cur) => (cur === f ? "todo" : f));

  // Danh sách ngăn phải theo bộ lọc. 要対応: lỗi trước, rồi nhiều 未認識, rồi nhiều 要確認.
  const items: PageItem[] = (r?.pages ?? []).map((p) => ({
    page: p.page,
    book: p.book_page,
    weak: p.current.weak,
    unread: p.current.unread,
    failed: false,
  }));
  const failed: PageItem[] = (r?.pages_failed ?? []).map((page) => ({ page, book: null, weak: 0, unread: 0, failed: true }));
  const byPage = (a: PageItem, b: PageItem) => a.page - b.page;
  const list: PageItem[] =
    filter === "all"
      ? [...items, ...failed].sort(byPage)
      : filter === "good"
        ? items.filter((p) => p.weak + p.unread === 0)
        : filter === "weak"
          ? items.filter((p) => p.weak > 0).sort((a, b) => b.weak - a.weak || byPage(a, b))
          : filter === "unread"
            ? items.filter((p) => p.unread > 0).sort((a, b) => b.unread - a.unread || byPage(a, b))
            : [
                ...failed,
                ...items
                  .filter((p) => p.weak + p.unread > 0)
                  .sort((a, b) => b.unread - a.unread || b.weak - a.weak || byPage(a, b)),
              ];

  /** Dòng bấm được để lọc ngăn phải; đang chọn → nền accent + vạch trái. */
  const selectable = (f: Filter, children: React.ReactNode, className?: string) => (
    <button
      type="button"
      aria-pressed={filter === f}
      onClick={() => pick(f)}
      className={cn(
        "block w-full cursor-pointer text-left transition-colors hover:bg-accent/40",
        filter === f && "bg-accent shadow-[inset_2px_0_0_var(--color-primary)] hover:bg-accent",
      )}
    >
      <PaneRow className={className}>{children}</PaneRow>
    </button>
  );
  const bucket = (k: "good" | "weak" | "unread", cur: number, ini: number, tone?: keyof typeof TONE) =>
    selectable(
      k,
      <>
        <span className="min-w-0 flex-1 truncate" title={t(`viewer.recognition.${k}Def`)}>
          {t(`viewer.recognition.${k}`)}
        </span>
        <Num n={cur} of={n} tone={tone} />
        <Num n={ini} of={n} />
      </>,
    );

  return (
    <>
      <Pane className={className}>
        <PaneHeader title={t("viewer.recognition.title")}>
          <PaneCol width={SUM_COL} className="text-xs font-medium text-muted-foreground">
            <span title={t("viewer.recognition.currentHint")}>{t("viewer.recognition.current")}</span>
          </PaneCol>
          <PaneCol width={SUM_COL} className="text-xs font-medium text-muted-foreground">
            <span title={t("viewer.recognition.initialHint")}>{t("viewer.recognition.initial")}</span>
          </PaneCol>
        </PaneHeader>
        {!r ? (
          <Loading />
        ) : n === 0 ? (
          <p className="px-5 py-3 text-sm text-muted-foreground">{t("viewer.recognition.none")}</p>
        ) : (
          <div className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
            {bucket("good", r.current.good + r.current.fixed, r.initial.good)}
            {r.current.fixed > 0 && (
              <PaneRow className="text-xs text-muted-foreground">
                <span className="min-w-0 flex-1 truncate pl-3">{t("viewer.recognition.fixed")}</span>
                <PaneCol width={SUM_COL}>
                  {pct(r.current.fixed, n)}%<span className="ml-1.5 inline-block min-w-8">{r.current.fixed}</span>
                </PaneCol>
                <PaneCol width={SUM_COL}>—</PaneCol>
              </PaneRow>
            )}
            {bucket("weak", r.current.weak, r.initial.weak, "warning")}
            {bucket("unread", r.current.unread, r.initial.unread, "danger")}
            {selectable(
              "all",
              <>
                <span className="flex-1">{t("viewer.recognition.total")}</span>
                <span className="tabular-nums">{t("viewer.recognition.elements", { n })}</span>
              </>,
              "text-muted-foreground",
            )}
            <div className="space-y-1 px-5 py-3 text-xs text-muted-foreground">
              <p>{t("viewer.recognition.rowHint")}</p>
              <p>{t("viewer.recognition.note")}</p>
              {r.pages_pending.length > 0 && <p>{t("viewer.recognition.pending", { n: r.pages_pending.length })}</p>}
              {r.estimated > 0 && <p>{t("viewer.recognition.estimated", { n: r.estimated })}</p>}
            </div>
          </div>
        )}
      </Pane>

      <Pane className={className}>
        <PaneHeader
          title={t(`viewer.recognition.${LIST_TITLE[filter]}`)}
          meta={r && !empty ? t("viewer.recognition.todoCount", { n: list.length, total: r.pages_total }) : undefined}
        >
          {filter !== "todo" && (
            <button
              type="button"
              onClick={() => setFilter("todo")}
              aria-label={t("viewer.recognition.backToTodo")}
              title={t("viewer.recognition.backToTodo")}
              className="-ml-1 grid size-6 shrink-0 cursor-pointer place-items-center rounded text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          )}
          <PaneCol width={PAGE_COL} className="text-xs font-medium text-muted-foreground">
            {t("viewer.recognition.colUnread")}
          </PaneCol>
          <PaneCol width={PAGE_COL} className="text-xs font-medium text-muted-foreground">
            {t("viewer.recognition.colWeak")}
          </PaneCol>
          <span className="w-4 shrink-0" aria-hidden />
        </PaneHeader>
        {!r ? (
          <Loading />
        ) : empty || list.length === 0 ? (
          <p className="px-5 py-3 text-sm text-muted-foreground">
            {t(
              empty
                ? "viewer.recognition.none"
                : filter === "todo"
                  ? "viewer.recognition.allGood"
                  : "viewer.recognition.noMatch",
            )}
          </p>
        ) : (
          <ul className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
            {list.map((p) => (
              <li key={`${p.failed ? "f" : "p"}${p.page}`}>
                <Link
                  to={`/documents/${docId}?tab=inspect&page=${p.page}`}
                  className="group block transition-colors hover:bg-accent/40"
                >
                  <PaneRow>
                    <span className="min-w-0 flex-1 truncate tabular-nums group-hover:underline">
                      p.{p.page}
                      {p.book !== null && <span className="ml-2 text-xs text-muted-foreground">P{p.book}</span>}
                    </span>
                    {p.failed ? (
                      <span className="text-danger">{t("viewer.recognition.failed")}</span>
                    ) : (
                      <>
                        <PaneCol width={PAGE_COL} className={p.unread ? "text-danger" : "text-muted-foreground"}>
                          {p.unread || "–"}
                        </PaneCol>
                        <PaneCol width={PAGE_COL} className={p.weak ? undefined : "text-muted-foreground"}>
                          {p.weak || "–"}
                        </PaneCol>
                      </>
                    )}
                    <ChevronRight
                      className="size-4 shrink-0 text-muted-foreground/60 group-hover:text-foreground"
                      aria-hidden
                    />
                  </PaneRow>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Pane>
    </>
  );
}
