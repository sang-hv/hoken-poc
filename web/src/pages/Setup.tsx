import { useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useErrorText } from "@/components/common";
import { Button, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { AuthLayout } from "./Login";

export default function SetupPage() {
  const { t } = useTranslation();
  const errText = useErrorText();
  const qc = useQueryClient();
  const nav = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const u = await api.post<User>("/setup", form);
      qc.setQueryData(["me"], u);
      qc.setQueryData(["setup-status"], { needs_setup: false });
      nav("/settings", { replace: true });
    } catch (err) {
      setError(errText(err));
      qc.invalidateQueries({ queryKey: ["setup-status"] });
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout>
      <div className="mb-5 flex items-start gap-3">
        <div className="rounded-xl bg-primary-soft p-2 text-primary">
          <ShieldCheck className="size-5" />
        </div>
        <div>
          <h1 className="text-lg font-semibold leading-tight">{t("auth.setupTitle")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("auth.setupDesc")}</p>
        </div>
      </div>
      <form className="flex flex-col gap-4" onSubmit={submit}>
        <Field label={t("common.name")}>
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label={t("auth.email")}>
          <Input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </Field>
        <Field label={t("auth.password")} hint={t("auth.passwordHint")}>
          <Input
            type="password"
            required
            minLength={10}
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
        </Field>
        {error && <p className="rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
        <Button type="submit" size="lg" loading={busy}>
          {t("auth.createAdmin")}
        </Button>
      </form>
    </AuthLayout>
  );
}
