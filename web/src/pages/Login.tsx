import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Languages } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useErrorText } from "@/components/common";
import { Button, Field, Input } from "@/components/ui";
import { LANGS } from "@/i18n";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

export function AuthLayout({ children }: { children: React.ReactNode }) {
  const { t, i18n } = useTranslation();
  return (
    <div className="relative flex min-h-full items-center justify-center overflow-hidden bg-background px-4 py-12">
      <div className="pointer-events-none absolute -top-40 left-1/2 size-[640px] -translate-x-1/2 rounded-full bg-primary/10 blur-3xl" />
      <div className="absolute right-4 top-4 flex items-center gap-1">
        <Languages className="size-4 text-muted-foreground" />
        {LANGS.map((l) => (
          <button
            key={l.code}
            onClick={() => i18n.changeLanguage(l.code)}
            className={`rounded-md px-2 py-1 text-sm ${i18n.language === l.code ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent"}`}
          >
            {l.label}
          </button>
        ))}
      </div>
      <div className="relative w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-lg">
            <svg viewBox="0 0 32 32" className="size-7">
              <path d="M9 16h14M16 9v14" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" />
            </svg>
          </div>
          <div>
            <p className="text-lg font-semibold">{t("app.name")}</p>
            <p className="text-sm text-muted-foreground">{t("app.tagline")}</p>
          </div>
        </div>
        <div className="rounded-2xl border border-border bg-card p-7 shadow-xl">{children}</div>
      </div>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-4">
      <path fill="#4285F4" d="M22.6 12.2c0-.8-.1-1.4-.2-2.1H12v4h6c-.1 1-.8 2.5-2.3 3.5v2.8h3.7c2.1-2 3.2-4.9 3.2-8.2z" />
      <path fill="#34A853" d="M12 23c3 0 5.6-1 7.4-2.7l-3.7-2.8c-1 .7-2.3 1.1-3.7 1.1-2.9 0-5.3-1.9-6.2-4.5H2v2.9C3.9 20.7 7.7 23 12 23z" />
      <path fill="#FBBC05" d="M5.8 14.1c-.2-.7-.4-1.4-.4-2.1s.1-1.4.4-2.1V7H2C1.3 8.5.9 10.2.9 12s.4 3.5 1.1 5l3.8-2.9z" />
      <path fill="#EA4335" d="M12 5.4c1.6 0 3.1.6 4.2 1.7l3.2-3.2C17.5 2.1 15 1 12 1 7.7 1 3.9 3.3 2 7l3.8 2.9c.9-2.6 3.3-4.5 6.2-4.5z" />
    </svg>
  );
}

function MicrosoftIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-4">
      <path fill="#F25022" d="M2 2h9.5v9.5H2z" />
      <path fill="#7FBA00" d="M12.5 2H22v9.5h-9.5z" />
      <path fill="#00A4EF" d="M2 12.5h9.5V22H2z" />
      <path fill="#FFB900" d="M12.5 12.5H22V22h-9.5z" />
    </svg>
  );
}

export default function LoginPage() {
  const { t } = useTranslation();
  const errText = useErrorText();
  const qc = useQueryClient();
  const nav = useNavigate();
  const loc = useLocation();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(params.get("error") ? t(`errors.${params.get("error")}`) : "");
  const providers = useQuery({
    queryKey: ["auth-providers"],
    queryFn: () => api.get<{ providers: string[] }>("/auth/providers"),
  });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const u = await api.post<User>("/auth/login", { email, password });
      qc.setQueryData(["me"], u);
      nav((loc.state as { from?: string } | null)?.from ?? "/", { replace: true });
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  };

  const sso = providers.data?.providers ?? [];
  return (
    <AuthLayout>
      <h1 className="text-xl font-semibold">{t("auth.signInTitle")}</h1>
      <p className="mb-6 mt-1 text-sm text-muted-foreground">{t("auth.signInDesc")}</p>
      {sso.length > 0 && (
        <>
          <div className="flex flex-col gap-2">
            {sso.includes("google") && (
              <Button variant="outline" onClick={() => (location.href = "/api/auth/oidc/google/start")}>
                <GoogleIcon />
                {t("auth.withGoogle")}
              </Button>
            )}
            {sso.includes("entra") && (
              <Button variant="outline" onClick={() => (location.href = "/api/auth/oidc/entra/start")}>
                <MicrosoftIcon />
                {t("auth.withEntra")}
              </Button>
            )}
          </div>
          <div className="my-5 flex items-center gap-3 text-xs text-muted-foreground">
            <div className="h-px flex-1 bg-border" />
            {t("auth.or")}
            <div className="h-px flex-1 bg-border" />
          </div>
        </>
      )}
      <form className="flex flex-col gap-4" onSubmit={submit}>
        <Field label={t("auth.email")} htmlFor="email">
          <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label={t("auth.password")} htmlFor="password">
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        {error && <p className="rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
        <Button type="submit" size="lg" loading={busy}>
          {busy ? t("auth.signingIn") : t("auth.signIn")}
        </Button>
      </form>
    </AuthLayout>
  );
}
