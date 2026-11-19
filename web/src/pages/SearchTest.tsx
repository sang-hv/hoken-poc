import { useQuery } from "@tanstack/react-query";
import { Database, Search } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Markdown, PageHeader, useErrorText } from "@/components/common";
import { Badge, Button, Card, CardContent, EmptyState, Input, Select } from "@/components/ui";
import { api } from "@/lib/api";
import type { SearchHit } from "@/lib/types";

export default function SearchPage() {
  const { t } = useTranslation();
  const errText = useErrorText();
  const [q, setQ] = useState("");
  const [k, setK] = useState("5");
  const [res, setRes] = useState<{ ms: number; hits: SearchHit[] } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const status = useQuery({
    queryKey: ["search-status"],
    queryFn: () => api.get<{ configured: boolean; count: number; error?: string }>("/search/status"),
  });

  const run = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    setError("");
    try {
      setRes(await api.post("/search", { q, k: Number(k) }));
    } catch (err) {
      setError(errText(err));
      setRes(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title={t("search.title")}
        subtitle={t("search.subtitle")}
        actions={
          status.data && (
            <Badge tone={status.data.configured ? "primary" : "warning"}>
              <Database />
              {status.data.configured ? t("search.indexed", { n: status.data.count }) : t("common.notConfigured")}
            </Badge>
          )
        }
      />
      <Card className="mb-6">
        <CardContent>
          <form className="flex flex-col gap-3 sm:flex-row" onSubmit={run}>
            <Input
              className="h-11 flex-1 text-base"
              placeholder={t("search.placeholder")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              autoFocus
            />
            <Select
              className="h-11 w-32"
              value={k}
              onValueChange={setK}
              options={["3", "5", "10", "20"].map((v) => ({ value: v, label: `${t("search.topK")}: ${v}` }))}
            />
            <Button type="submit" size="lg" loading={busy}>
              <Search />
              {t("search.run")}
            </Button>
          </form>
          {error && <p className="mt-3 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
        </CardContent>
      </Card>
      {res && (
        <>
          <p className="mb-3 text-sm text-muted-foreground">{t("search.results", { n: res.hits.length, ms: res.ms })}</p>
          {res.hits.length === 0 && <EmptyState icon={<Search />} title={t("search.noResults")} />}
          <ol className="flex flex-col gap-3">
            {res.hits.map((h, i) => (
              <Card key={h.id}>
                <CardContent className="flex flex-col gap-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="flex size-6 items-center justify-center rounded-full bg-primary-soft text-xs font-semibold text-primary">
                      {i + 1}
                    </span>
                    <Badge tone="primary" className="font-mono">
                      {h.item_code || "—"}
                    </Badge>
                    <Link to={`/documents/${h.doc_id}`} className="text-sm font-medium hover:text-primary">
                      {h.doc_name}
                    </Link>
                    <span className="text-sm text-muted-foreground">
                      P{h.page_from}
                      {h.page_to !== h.page_from ? `–${h.page_to}` : ""}
                    </span>
                    <div className="flex-1" />
                    {Object.entries(h.scores).map(([name, v]) => (
                      <Badge key={name} className="font-mono">
                        {name} {v.toFixed(3)}
                      </Badge>
                    ))}
                    <Badge tone="violet" className="font-mono">
                      {t("search.score")} {h.score.toFixed(4)}
                    </Badge>
                  </div>
                  <div className="max-h-64 overflow-auto rounded-lg bg-muted/50 p-3">
                    <Markdown text={h.content} />
                  </div>
                </CardContent>
              </Card>
            ))}
          </ol>
        </>
      )}
    </>
  );
}
