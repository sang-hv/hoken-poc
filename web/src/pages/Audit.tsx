import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/common";
import { Badge, Card, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDateTime } from "@/lib/utils";

interface Entry {
  id: string;
  actor: string;
  action: string;
  target: string;
  detail: Record<string, unknown>;
  at: string;
}

export default function AuditPage() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["audit"], queryFn: () => api.get<Entry[]>("/audit"), refetchInterval: 10000 });
  return (
    <>
      <PageHeader title={t("audit.title")} subtitle={t("audit.subtitle")} />
      <Card>
        {q.isLoading && <Skeleton className="m-4 h-40" />}
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
              {q.data?.map((e) => (
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
      </Card>
    </>
  );
}
