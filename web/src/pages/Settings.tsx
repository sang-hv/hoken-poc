import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Copy,
  Database,
  KeyRound,
  Lock,
  PlugZap,
  Save,
  Server,
  SlidersHorizontal,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { PageHeader, useErrorText, useToastError } from "@/components/common";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Field,
  Input,
  Select,
  Skeleton,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from "@/components/ui";
import { api } from "@/lib/api";
import type { AdapterSpec, FieldSpec, ProvidersResponse } from "@/lib/types";
import { cn, fmtDateTime } from "@/lib/utils";

/* ================================================================ System (lớp 1, chỉ đọc) */
function SystemTab() {
  const { t } = useTranslation();
  const sys = useQuery({
    queryKey: ["system"],
    queryFn: () =>
      api.get<{
        bootstrap: Record<string, string>;
        health: Record<string, { ok: boolean; ms?: number; error?: string }>;
      }>("/system"),
  });
  if (!sys.data) return <Skeleton className="h-60" />;
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Lock className="size-4 text-muted-foreground" />
            {t("settings.environment")}
          </CardTitle>
          <CardDescription>{t("settings.systemDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="divide-y divide-border rounded-lg border border-border">
            {Object.entries(sys.data.bootstrap).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between gap-4 px-3 py-2 text-sm">
                <dt className="font-mono text-xs text-muted-foreground">{k}</dt>
                <dd className="truncate font-medium">{v || "—"}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="size-4 text-muted-foreground" />
            {t("settings.health")}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {Object.entries(sys.data.health).map(([k, h]) => (
            <div key={k} className="flex items-center justify-between rounded-lg border border-border px-3 py-2.5 text-sm">
              <span className="font-medium uppercase">{k}</span>
              {h.ok ? (
                <Badge tone="success">
                  <CheckCircle2 />
                  {t("settings.healthy")} · {h.ms} ms
                </Badge>
              ) : (
                <Badge tone="danger" title={h.error}>
                  <XCircle />
                  {t("settings.unhealthy")}
                </Badge>
              )}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

/* ================================================================ Services (lớp 2) */
const COMPONENT_ICON: Record<string, React.ReactNode> = {
  llm: <BrainCircuit />,
  embedding: <SlidersHorizontal />,
  cu: <PlugZap />,
  search: <Database />,
};

function fieldLabel(t: (k: string, o?: Record<string, unknown>) => string, name: string) {
  return t(`settings.fields.${name}`, { defaultValue: name });
}

function visible(f: FieldSpec, values: Record<string, unknown>) {
  return Object.entries(f.show_if ?? {}).every(([k, v]) => values[k] === v);
}

function ServiceCard({ component, data }: { component: string; data: ProvidersResponse }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();
  const errText = useErrorText();
  const specs = data.catalog[component] ?? [];
  const current = data.components[component];
  const [type, setType] = useState<string>(current?.type ?? specs[0]?.type ?? "");
  const spec = specs.find((s) => s.type === type) as AdapterSpec | undefined;
  const sameType = current?.type === type;
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"test" | "save" | null>(null);
  const [test, setTest] = useState<{ ok: boolean; ms?: number; error?: string } | null>(null);

  useEffect(() => {
    if (!spec) return;
    const v: Record<string, unknown> = {};
    for (const f of spec.fields) {
      if (f.kind === "secret") continue;
      const cur = sameType ? current?.config[f.name] : undefined;
      const def = typeof f.default === "string" && f.default.includes("<") ? "" : f.default;
      v[f.name] = cur ?? def ?? (f.kind === "bool" ? false : "");
    }
    setValues(v);
    setSecrets({});
    setTest(null);
  }, [type, spec, sameType, current]);

  const payload = () => ({ type, config: values, secrets });

  const doTest = async () => {
    setBusy("test");
    try {
      setTest(await api.post(`/settings/providers/${component}/test`, payload()));
    } catch (e) {
      setTest({ ok: false, error: errText(e) });
    } finally {
      setBusy(null);
    }
  };
  const doSave = async () => {
    setBusy("save");
    try {
      const r = await api.put<ProvidersResponse>(`/settings/providers/${component}`, payload());
      qc.setQueryData(["providers"], r);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success(t("settings.savedVersion", { v: r.version }));
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="rounded-xl bg-primary-soft p-2 text-primary [&_svg]:size-5">{COMPONENT_ICON[component]}</div>
          <div>
            <CardTitle>{t(`settings.component.${component}`)}</CardTitle>
            <CardDescription>{t(`settings.componentDesc.${component}`)}</CardDescription>
          </div>
        </div>
        {current ? (
          <Badge tone="success">
            <CheckCircle2 />
            {t(`settings.types.${current.type}`)}
          </Badge>
        ) : (
          <Badge tone="warning">{t("common.notConfigured")}</Badge>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-2">
          {specs.map((s) => (
            <button
              key={s.type}
              type="button"
              onClick={() => setType(s.type)}
              className={cn(
                "flex min-w-36 flex-1 flex-col items-start rounded-lg border px-3 py-2 text-left transition",
                type === s.type ? "border-primary bg-primary-soft/60 ring-2 ring-primary/15" : "border-border hover:bg-accent",
              )}
            >
              <span className="text-sm font-semibold">{t(`settings.types.${s.type}`)}</span>
              <span className="text-xs text-muted-foreground">{s.service}</span>
            </button>
          ))}
        </div>
        {spec && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {spec.fields
              .filter((f) => visible(f, values))
              .map((f) => {
                const label = (
                  <span>
                    {fieldLabel(t, f.name)}
                    {f.required && <span className="text-danger"> *</span>}
                  </span>
                );
                if (f.kind === "secret") {
                  const stored = sameType && current?.secrets_set.includes(f.name);
                  return (
                    <Field
                      key={f.name}
                      label={
                        <span className="flex items-center gap-1.5">
                          <KeyRound className="size-3.5 text-muted-foreground" />
                          {label}
                        </span>
                      }
                      hint={stored ? t("settings.secretSet") : t("settings.secretNotSet")}
                    >
                      <Input
                        type="password"
                        autoComplete="new-password"
                        placeholder={stored ? "••••••••••••" : ""}
                        value={secrets[f.name] ?? ""}
                        onChange={(e) => setSecrets({ ...secrets, [f.name]: e.target.value })}
                      />
                    </Field>
                  );
                }
                if (f.kind === "select")
                  return (
                    <Field key={f.name} label={label}>
                      <Select
                        value={String(values[f.name] ?? "")}
                        onValueChange={(v) => setValues({ ...values, [f.name]: v })}
                        options={f.options.map((o) => ({ value: o, label: t(`settings.authOptions.${o}`, { defaultValue: o }) }))}
                      />
                    </Field>
                  );
                if (f.kind === "bool")
                  return (
                    <Field key={f.name} label={label}>
                      <Switch checked={!!values[f.name]} onCheckedChange={(v) => setValues({ ...values, [f.name]: v })} />
                    </Field>
                  );
                return (
                  <Field key={f.name} label={label}>
                    <Input
                      type={f.kind === "number" ? "number" : "text"}
                      step="any"
                      value={String(values[f.name] ?? "")}
                      placeholder={typeof f.default === "string" ? f.default : ""}
                      onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                    />
                  </Field>
                );
              })}
          </div>
        )}
        {component === "search" && (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <AlertTriangle className="size-3.5 text-warning" />
            {t("settings.reindexWarn")}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
          {test && (
            <Badge tone={test.ok ? "success" : "danger"} className="max-w-full whitespace-normal">
              {test.ok ? <CheckCircle2 /> : <XCircle />}
              {test.ok ? t("settings.testOk", { ms: test.ms }) : `${t("settings.testFail")}: ${test.error ?? ""}`}
            </Badge>
          )}
          <div className="flex-1" />
          <Button variant="outline" onClick={doTest} loading={busy === "test"}>
            <PlugZap />
            {busy === "test" ? t("settings.testing") : t("settings.test")}
          </Button>
          <Button onClick={doSave} loading={busy === "save"}>
            <Save />
            {t("settings.saveService")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ServicesTab() {
  const { t } = useTranslation();
  const providers = useQuery({ queryKey: ["providers"], queryFn: () => api.get<ProvidersResponse>("/settings/providers") });
  const system = useQuery({ queryKey: ["system"], queryFn: () => api.get<{ bootstrap: Record<string, string> }>("/system") });
  if (!providers.data) return <Skeleton className="h-96" />;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-muted/60 px-4 py-3 text-sm text-muted-foreground">
        <span>{t("settings.servicesDesc")}</span>
        <span className="flex items-center gap-2">
          {system.data?.bootstrap.app_env === "prod" && <Badge tone="info">{t("settings.prodNoLocal")}</Badge>}
          {providers.data.version > 0 && (
            <Badge>
              v{providers.data.version} · {providers.data.updated_by} · {fmtDateTime(providers.data.updated_at)}
            </Badge>
          )}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        {(["llm", "embedding", "cu", "search"] as const).map((c) => (
          <ServiceCard key={c} component={c} data={providers.data} />
        ))}
      </div>
    </div>
  );
}

/* ================================================================ Pipeline (lớp 4) */
type Opts = Record<string, Record<string, unknown>>;

function PipelineTab() {
  const { t } = useTranslation();
  const toastError = useToastError();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["pipeline"],
    queryFn: () => api.get<{ version: number; options: Opts; updated_by: string; updated_at: string }>("/settings/pipeline"),
  });
  const [opts, setOpts] = useState<Opts | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (q.data) setOpts(structuredClone(q.data.options));
  }, [q.data]);
  const dirty = useMemo(() => JSON.stringify(opts) !== JSON.stringify(q.data?.options), [opts, q.data]);
  if (!opts || !q.data) return <Skeleton className="h-96" />;

  const set = (section: string, key: string, value: unknown) =>
    setOpts({ ...opts, [section]: { ...opts[section], [key]: value } });

  const save = async () => {
    setBusy(true);
    try {
      const r = await api.put<{ version: number }>("/settings/pipeline", { options: opts });
      toast.success(t("settings.pipelineSaved", { v: r.version }));
      qc.invalidateQueries({ queryKey: ["pipeline"] });
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(false);
    }
  };

  const control = (section: string, key: string, value: unknown) => {
    const label = t(`settings.opts.${key}`, { defaultValue: key });
    if (typeof value === "boolean")
      return (
        <label key={key} className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5 text-sm">
          {label}
          <Switch checked={value} onCheckedChange={(v) => set(section, key, v)} />
        </label>
      );
    if (key === "table_mode")
      return (
        <Field key={key} label={label}>
          <Select
            value={String(value)}
            onValueChange={(v) => set(section, key, v)}
            options={["accurate", "fast"].map((o) => ({ value: o, label: o }))}
          />
        </Field>
      );
    if (Array.isArray(value))
      return (
        <Field key={key} label={label}>
          <Input
            value={value.join(", ")}
            onChange={(e) =>
              set(
                section,
                key,
                e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
              )
            }
          />
        </Field>
      );
    if (typeof value === "number")
      return (
        <Field key={key} label={label}>
          <Input type="number" step="any" value={value} onChange={(e) => set(section, key, Number(e.target.value))} />
        </Field>
      );
    const long = String(value).length > 80 || key.includes("prompt");
    return (
      <Field key={key} label={label} className={long ? "sm:col-span-2" : ""}>
        {long ? (
          <Textarea rows={4} className="font-mono text-xs" value={String(value)} onChange={(e) => set(section, key, e.target.value)} />
        ) : (
          <Input className="font-mono text-xs" value={String(value)} onChange={(e) => set(section, key, e.target.value)} />
        )}
      </Field>
    );
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card/90 px-4 py-3 shadow-card backdrop-blur">
        <span className="text-sm text-muted-foreground">{t("settings.pipelineDesc")}</span>
        <span className="flex items-center gap-2">
          <Badge>
            v{q.data.version}
            {q.data.updated_by ? ` · ${q.data.updated_by}` : ""}
          </Badge>
          <Button variant="ghost" disabled={!dirty} onClick={() => setOpts(structuredClone(q.data.options))}>
            {t("common.reset")}
          </Button>
          <Button onClick={save} disabled={!dirty} loading={busy}>
            <Save />
            {t("common.save")}
          </Button>
        </span>
      </div>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        {Object.entries(opts).map(([section, values]) => (
          <Card key={section} className={["chunk", "cu", "chat", "quality"].includes(section) ? "xl:col-span-2" : ""}>
            <CardHeader>
              <CardTitle>{t(`settings.sections.${section}`, { defaultValue: section })}</CardTitle>
              {section === "routing" && <CardDescription>{t("routing.desc")}</CardDescription>}
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              {/* Công tắc một nhóm, ô nhập một nhóm: Field là subgrid 3 hàng nên không xếp xen kẽ với công tắc */}
              {Object.values(values).some((v) => typeof v === "boolean") && (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {Object.entries(values)
                    .filter(([, v]) => typeof v === "boolean")
                    .map(([k, v]) => control(section, k, v))}
                </div>
              )}
              {Object.values(values).some((v) => typeof v !== "boolean") && (
                <div className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2">
                  {Object.entries(values)
                    .filter(([, v]) => typeof v !== "boolean")
                    .map(([k, v]) => control(section, k, v))}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

/* ================================================================ SSO */
interface AuthCfg {
  enabled: boolean;
  client_id: string;
  tenant_id?: string;
  allowed_domains: string;
  default_role: string;
  secrets_set: string[];
}

function AuthProviderCard({ name, cfg, redirect }: { name: "google" | "entra"; cfg: AuthCfg; redirect: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();
  const [form, setForm] = useState({ ...cfg, client_secret: "" });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.put(`/settings/auth/${name}`, form);
      toast.success(t("common.saved"));
      qc.invalidateQueries({ queryKey: ["auth-settings"] });
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>{t(`settings.${name}`)}</CardTitle>
        <label className="flex items-center gap-2 text-sm">
          {t("settings.enable")}
          <Switch checked={form.enabled} onCheckedChange={(v) => setForm({ ...form, enabled: v })} />
        </label>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label={t("settings.redirectUri")} className="sm:col-span-2">
          <div className="flex gap-2">
            <Input readOnly value={redirect} className="font-mono text-xs" />
            <Button
              variant="outline"
              size="icon"
              onClick={() => {
                navigator.clipboard.writeText(redirect);
                toast.success(t("common.copy"));
              }}
            >
              <Copy />
            </Button>
          </div>
        </Field>
        {name === "entra" && (
          <Field label={t("settings.tenantId")}>
            <Input value={form.tenant_id ?? ""} onChange={(e) => setForm({ ...form, tenant_id: e.target.value })} />
          </Field>
        )}
        <Field label={t("settings.clientId")}>
          <Input value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} />
        </Field>
        <Field
          label={t("settings.clientSecret")}
          hint={cfg.secrets_set.includes("client_secret") ? t("settings.secretSet") : t("settings.secretNotSet")}
        >
          <Input
            type="password"
            autoComplete="new-password"
            placeholder={cfg.secrets_set.includes("client_secret") ? "••••••••••••" : ""}
            value={form.client_secret}
            onChange={(e) => setForm({ ...form, client_secret: e.target.value })}
          />
        </Field>
        <Field label={t("settings.allowedDomains")}>
          <Input
            value={form.allowed_domains}
            placeholder="example.co.jp"
            onChange={(e) => setForm({ ...form, allowed_domains: e.target.value })}
          />
        </Field>
        <Field label={t("settings.defaultRole")}>
          <Select
            value={form.default_role || "viewer"}
            onValueChange={(v) => setForm({ ...form, default_role: v })}
            options={["viewer", "reviewer"].map((r) => ({ value: r, label: t(`roles.${r}`) }))}
          />
        </Field>
        <div className="flex justify-end sm:col-span-2">
          <Button onClick={save} loading={busy}>
            <Save />
            {t("common.save")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function AuthTab() {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ["auth-settings"],
    queryFn: () =>
      api.get<{ providers: Record<"google" | "entra", AuthCfg>; redirect_uris: Record<string, string> }>("/settings/auth"),
  });
  if (!q.data) return <Skeleton className="h-80" />;
  return (
    <div className="flex flex-col gap-6">
      <p className="rounded-xl bg-muted/60 px-4 py-3 text-sm text-muted-foreground">{t("settings.authDesc")}</p>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        {(["google", "entra"] as const).map((n) => (
          <AuthProviderCard key={n} name={n} cfg={q.data.providers[n]} redirect={q.data.redirect_uris[n]} />
        ))}
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "services";
  return (
    <>
      <PageHeader title={t("settings.title")} subtitle={t("settings.subtitle")} />
      <Tabs value={tab} onValueChange={(v) => setParams({ tab: v }, { replace: true })}>
        <TabsList className="mb-6">
          <TabsTrigger value="services">
            <BrainCircuit />
            {t("settings.services")}
          </TabsTrigger>
          <TabsTrigger value="pipeline">
            <SlidersHorizontal />
            {t("settings.pipeline")}
          </TabsTrigger>
          <TabsTrigger value="auth">
            <KeyRound />
            {t("settings.auth")}
          </TabsTrigger>
          <TabsTrigger value="system">
            <Server />
            {t("settings.system")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="services">
          <ServicesTab />
        </TabsContent>
        <TabsContent value="pipeline">
          <PipelineTab />
        </TabsContent>
        <TabsContent value="auth">
          <AuthTab />
        </TabsContent>
        <TabsContent value="system">
          <SystemTab />
        </TabsContent>
      </Tabs>
    </>
  );
}
