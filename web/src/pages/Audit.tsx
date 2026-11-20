import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ScrollText } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { PageHeader, Pagination } from "@/components/common";
import { Badge, Card, EmptyState, Input, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useDebounced } from "@/lib/hooks";
import { fmtDateTime } from "@/lib/utils";

interface Entry {
  id: string;
  actor: string;
  action: string;
  target: string;
  detail: Record<string, unknown>;
  at: string;
}

const AUDIT_PAGE = 50;

export default function AuditPage() {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  // Tìm phía server → debounce; đổi từ khoá thì về trang 1
  const debounced = useDebounced(search.trim(), 300);
  useEffect(() => setPage(1), [debounced]);
  const params = new URLSearchParams({ paged: "true", limit: String(AUDIT_PAGE), offset: String((page - 1) * AUDIT_PAGE) });
  if (debounced) params.set("q", debounced);
  const q = useQuery({
    queryKey: ["audit", debounced, page],
    queryFn: () => api.get<{ items: Entry[]; total: number }>(`/audit?${params}`),
    refetchInterval: 10000,
    placeholderData: keepPreviousData,
  });
  return (
    <>
      <PageHeader title={t("audit.title")} subtitle={t("audit.subtitle")} />
      <Card>
        <div className="border-b border-border px-4 py-3">
          <Input
            type="search"
            className="w-full sm:max-w-sm"
            placeholder={t("audit.searchPlaceholder")}
            aria-label={t("audit.searchPlaceholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {q.isLoading && <Skeleton className="m-4 h-40" />}
        {q.data && q.data.items.length === 0 && (
          <EmptyState icon={<ScrollText />} title={debounced ? t("common.noMatch") : t("common.empty")} />
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr className="border-b border-border">
                <th className="px-4 py-2.5 font-medium">{t("audit.at")}</th>
                <th className="px-3 py-2.5 font-medium">{t("audit.actor")}</th>
                <th className="px-3 py-2.5 font-medium">{t("audit.action")}</th>
                <th className="px-3 py-2.5 font-medium">{t("audit.target")}</th>
                <th className="px-3 py-2.5 font-medium">{t("audit.detail")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {q.data?.items.map((e) => (
                <tr key={e.id}>
                  <td className="whitespace-nowrap px-4 py-2 text-muted-foreground">{fmtDateTime(e.at)}</td>
                  <td className="px-3 py-2">{e.actor}</td>
                  <td className="px-3 py-2">
                    <Badge tone="primary" className="font-mono">
                      {e.action}
                    </Badge>
                  </td>
                  <td className="max-w-48 truncate px-3 py-2 font-mono text-xs text-muted-foreground">{e.target}</td>
                  <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                    {Object.entries(e.detail)
                      .map(([k, v]) => `${k}=${String(v)}`)
                      .join("  ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {q.data && <Pagination page={page} size={AUDIT_PAGE} total={q.data.total} onPage={setPage} />}
      </Card>
    </>
  );
}
