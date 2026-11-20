import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, Trash2, UserPlus } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ConfirmDialog, PageHeader, Pagination, useToastError } from "@/components/common";
import { Badge, Button, Card, Dialog, EmptyState, Field, Input, Select, Skeleton, Switch } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useClientPage } from "@/lib/hooks";
import type { Role, User } from "@/lib/types";
import { fmtRelative } from "@/lib/utils";

const ROLES: Role[] = ["admin", "reviewer", "viewer"];
const USERS_PAGE = 20;

export function ChangePasswordDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const toastError = useToastError();
  const [form, setForm] = useState({ current: "", new: "" });
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("common.changePassword")}
      footer={
        <Button
          loading={busy}
          disabled={form.new.length < 10}
          onClick={async () => {
            setBusy(true);
            try {
              await api.post("/me/password", form);
              toast.success(t("common.saved"));
              onOpenChange(false);
              setForm({ current: "", new: "" });
            } catch (e) {
              toastError(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          {t("common.save")}
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        <Field label={t("auth.currentPassword")}>
          <Input type="password" value={form.current} onChange={(e) => setForm({ ...form, current: e.target.value })} />
        </Field>
        <Field label={t("auth.newPassword")} hint={t("auth.passwordHint")}>
          <Input
            type="password"
            autoComplete="new-password"
            value={form.new}
            onChange={(e) => setForm({ ...form, new: e.target.value })}
          />
        </Field>
      </div>
    </Dialog>
  );
}

function AddUserDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toastError = useToastError();
  const [form, setForm] = useState({ email: "", name: "", role: "reviewer" as Role, password: "" });
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("users.invite")}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button
            loading={busy}
            disabled={!form.email}
            onClick={async () => {
              setBusy(true);
              try {
                await api.post("/users", { ...form, password: form.password || null });
                qc.invalidateQueries({ queryKey: ["users"] });
                onOpenChange(false);
                setForm({ email: "", name: "", role: "reviewer", password: "" });
              } catch (e) {
                toastError(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            <UserPlus />
            {t("users.invite")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field label={t("common.email")}>
          <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </Field>
        <Field label={t("common.name")}>
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label={t("common.role")} hint={t(`roles.${form.role}Desc`)}>
          <Select
            value={form.role}
            onValueChange={(v) => setForm({ ...form, role: v as Role })}
            options={ROLES.map((r) => ({ value: r, label: t(`roles.${r}`) }))}
          />
        </Field>
        <Field label={t("users.passwordOptional")} hint={t("auth.passwordHint")}>
          <Input
            type="password"
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
        </Field>
      </div>
    </Dialog>
  );
}

export default function UsersPage() {
  const { t } = useTranslation();
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const toastError = useToastError();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api.get<User[]>("/users") });
  const [open, setOpen] = useState(false);
  const [toDelete, setToDelete] = useState<User | null>(null);
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("all");
  const [page, setPage] = useState(1);
  const list = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (users.data ?? []).filter(
      (u) => (!needle || `${u.name} ${u.email}`.toLowerCase().includes(needle)) && (role === "all" || u.role === role),
    );
  }, [users.data, search, role]);
  const paged = useClientPage(list, page, USERS_PAGE);
  const filtered = !!search.trim() || role !== "all";
  const patch = async (u: User, body: Partial<User>) => {
    try {
      await api.patch(`/users/${u.id}`, body);
      qc.invalidateQueries({ queryKey: ["users"] });
    } catch (e) {
      toastError(e);
    }
  };
  return (
    <>
      <PageHeader
        title={t("users.title")}
        subtitle={t("users.subtitle")}
        actions={
          <Button onClick={() => setOpen(true)}>
            <UserPlus />
            {t("users.invite")}
          </Button>
        }
      />
      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {ROLES.map((r) => (
          <div key={r} className="rounded-xl border border-border bg-card px-4 py-3 shadow-card">
            <p className="text-sm font-semibold">{t(`roles.${r}`)}</p>
            <p className="text-xs text-muted-foreground">{t(`roles.${r}Desc`)}</p>
          </div>
        ))}
      </div>
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <Input
            type="search"
            className="w-full sm:max-w-xs sm:flex-1"
            placeholder={t("users.searchPlaceholder")}
            aria-label={t("users.searchPlaceholder")}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
          <Select
            className="w-full sm:w-44"
            aria-label={t("common.role")}
            value={role}
            onValueChange={(v) => {
              setRole(v);
              setPage(1);
            }}
            options={[{ value: "all", label: t("users.allRoles") }, ...ROLES.map((r) => ({ value: r, label: t(`roles.${r}`) }))]}
          />
        </div>
        {users.isLoading && <Skeleton className="m-4 h-40" />}
        {users.data && list.length === 0 && <EmptyState icon={<Search />} title={filtered ? t("common.noMatch") : t("common.empty")} />}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr className="border-b border-border">
                <th className="px-4 py-2.5 font-medium">{t("common.email")}</th>
                <th className="px-3 py-2.5 font-medium">{t("common.role")}</th>
                <th className="px-3 py-2.5 font-medium">{t("users.provider")}</th>
                <th className="px-3 py-2.5 font-medium">{t("users.active")}</th>
                <th className="px-3 py-2.5 font-medium">{t("users.lastLogin")}</th>
                <th />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {paged.items.map((u) => (
                <tr key={u.id}>
                  <td className="px-4 py-2.5">
                    <p className="font-medium">{u.name || u.email}</p>
                    {u.name && <p className="text-xs text-muted-foreground">{u.email}</p>}
                  </td>
                  <td className="px-3 py-2.5">
                    <Select
                      className="h-8 w-36"
                      value={u.role}
                      disabled={u.id === me?.id}
                      onValueChange={(v) => patch(u, { role: v as Role })}
                      options={ROLES.map((r) => ({ value: r, label: t(`roles.${r}`) }))}
                    />
                  </td>
                  <td className="px-3 py-2.5">
                    <Badge>{u.provider}</Badge>
                  </td>
                  <td className="px-3 py-2.5">
                    <Switch checked={u.active} disabled={u.id === me?.id} onCheckedChange={(v) => patch(u, { active: v })} />
                  </td>
                  <td className="px-3 py-2.5 text-muted-foreground">{fmtRelative(u.last_login_at)}</td>
                  <td className="px-3 py-2.5 text-right">
                    {u.id !== me?.id && (
                      <Button variant="ghost" size="iconSm" onClick={() => setToDelete(u)} aria-label={t("common.delete")}>
                        <Trash2 className="text-danger" />
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination page={paged.page} size={USERS_PAGE} total={paged.total} onPage={setPage} />
      </Card>
      <AddUserDialog open={open} onOpenChange={setOpen} />
      <ConfirmDialog
        open={!!toDelete}
        onOpenChange={(o) => !o && setToDelete(null)}
        title={t("common.delete")}
        description={toDelete ? t("users.deleteConfirm", { email: toDelete.email }) : ""}
        danger
        onConfirm={async () => {
          try {
            await api.del(`/users/${toDelete!.id}`);
            qc.invalidateQueries({ queryKey: ["users"] });
          } catch (e) {
            toastError(e);
          }
        }}
      />
    </>
  );
}
