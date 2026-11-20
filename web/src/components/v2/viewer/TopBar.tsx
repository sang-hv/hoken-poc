import { ChevronLeft, Download, ExternalLink, FileImage, FileText, Layers, MoreHorizontal, ScanText, Workflow } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  Button,
  buttonVariants,
  Dropdown,
  DropdownContent,
  DropdownItem,
  DropdownSeparator,
  DropdownTrigger,
  Skeleton,
} from "@/components/ui";
import type { DocInfo } from "@/lib/v2types";
import { cn } from "@/lib/utils";
import { VIEWER_TABS, type ViewerTab } from "./shared";

/** Thanh trên: "‹ 文書", tên tài liệu, 5 tab dạng segmented, menu その他. */
export function TopBar({
  docId,
  info,
  infoLoading,
  tab,
  onTab,
  page,
}: {
  docId: string;
  info?: DocInfo;
  infoLoading: boolean;
  tab: ViewerTab;
  onTab: (t: ViewerTab) => void;
  page: number;
}) {
  const { t } = useTranslation();
  const source = `/api/documents/${docId}/source`;
  const Icon = info?.file_type === "image" ? FileImage : FileText;

  return (
    <header className="grid shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 border-b border-border bg-card px-3 py-2 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
      <div className="flex min-w-0 items-center gap-1 lg:col-start-1 lg:row-start-1">
        <Link
          to="/documents"
          aria-label={t("viewer.top.back")}
          title={t("viewer.top.back")}
          className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "min-w-0 shrink-0 gap-1 px-2 text-muted-foreground")}
        >
          <ChevronLeft />
          <span className="hidden max-w-44 truncate sm:inline">{t("nav.documents")}</span>
        </Link>
        <span className="mx-1 hidden h-5 w-px bg-border sm:block" aria-hidden />
        <Icon className="size-4 shrink-0 text-danger" aria-hidden />
        {infoLoading ? (
          <Skeleton className="h-4 w-48" />
        ) : (
          <h1 className="min-w-0 truncate text-sm font-semibold" title={info?.name}>
            {info?.name ?? ""}
          </h1>
        )}
      </div>

      <div
        role="tablist"
        aria-label={t("viewer.tabs.label")}
        className="col-span-2 row-start-2 flex items-center justify-self-center rounded-lg bg-muted p-1 lg:col-span-1 lg:col-start-2 lg:row-start-1"
        onKeyDown={(e) => {
          if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
          e.preventDefault();
          e.stopPropagation();
          const i = VIEWER_TABS.indexOf(tab);
          const n = VIEWER_TABS[(i + (e.key === "ArrowRight" ? 1 : VIEWER_TABS.length - 1)) % VIEWER_TABS.length];
          onTab(n);
          (e.currentTarget.querySelector(`[data-tab="${n}"]`) as HTMLElement | null)?.focus();
        }}
      >
        {VIEWER_TABS.map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            data-tab={k}
            aria-selected={tab === k}
            tabIndex={tab === k ? 0 : -1}
            onClick={() => onTab(k)}
            className={cn(
              "flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1.5 text-sm font-medium transition sm:px-3.5",
              tab === k ? "bg-card text-foreground shadow-card" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {k === "pipeline" && <Workflow className="size-4" aria-hidden />}
            {k === "chunks" && <Layers className="size-4" aria-hidden />}
            {k === "inspect" && <ScanText className="size-4" aria-hidden />}
            {t(`viewer.tabs.${k}`)}
          </button>
        ))}
      </div>

      <div className="flex justify-end lg:col-start-3 lg:row-start-1">
        <Dropdown>
          <DropdownTrigger asChild>
            <Button variant="ghost" size="sm" aria-label={t("viewer.top.more")}>
              <MoreHorizontal />
              <span className="hidden sm:inline">{t("viewer.top.more")}</span>
            </Button>
          </DropdownTrigger>
          <DropdownContent>
            <DropdownItem asChild>
              <a href={source} target="_blank" rel="noreferrer">
                <ExternalLink />
                {t("viewer.top.openPdf")}
              </a>
            </DropdownItem>
            <DropdownItem asChild>
              <a href={source} download={info?.filename || true}>
                <Download />
                {t("viewer.top.downloadPdf")}
              </a>
            </DropdownItem>
            <DropdownSeparator />
            <DropdownItem asChild>
              <Link to={`/documents/${docId}/pages/${Math.max(1, page)}`}>
                <ScanText />
                {t("viewer.top.classicReview")}
              </Link>
            </DropdownItem>
          </DropdownContent>
        </Dropdown>
      </div>
    </header>
  );
}
