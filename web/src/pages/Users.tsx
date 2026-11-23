import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Search, Trash2, UserCheck, UserPlus, UserX } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ConfirmDialog, PageHeader, Pagination, useToastError } from "@/components/common";
import {
  Button,
  Dialog,
  Dropdown,
  DropdownContent,
  DropdownItem,
  DropdownSeparator,
  DropdownTrigger,
  EmptyState,
  Field,
  FilterChips,
  Input,
  Select,
  Skeleton,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useClientPage } from "@/lib/hooks";
import type { Role, User } from "@/lib/types";
import { cn, fmtRelative } from "@/lib/utils";

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

function RowMenu({
  u,
  onActive,
  onDelete,
}: {
  u: User;
  onActive: (u: User, active: boolean) => void;
  onDelete: (u: User) => void;
}) {
  const { t } = useTranslation();
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <Button variant="ghost" size="iconSm" aria-label={t("common.actions")}>
          <MoreHorizontal />
        </Button>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownItem onSelect={() => onActive(u, !u.active)}>
          {u.active ? <UserX /> : <UserCheck />}
          {u.active ? t("users.deactivate") : t("users.activate")}
        </DropdownItem>
        <DropdownSeparator />
        <DropdownItem className="text-danger [&_svg]:text-danger" onSelect={() => onDelete(u)}>
          <Trash2 />
          {t("common.delete")}
        </DropdownItem>
      </DropdownContent>
    </Dropdown>
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
  const [toDisable, setToDisable] = useState<User | null>(null);
  const [search, setSearch] = useState("");
  const [role, setRole] = useState<"all" | Role>("all");
  const [page, setPage] = useState(1);
  const all = users.data ?? [];
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
      toast.success(t("common.saved"));
      qc.invalidateQueries({ queryKey: ["users"] });
    } catch (e) {
      toastError(e);
    }
  };
  // Tắt đăng nhập phải xác nhận; bật lại thì làm luôn
  const setActive = (u: User, active: boolean) => (active ? patch(u, { active }) : setToDisable(u));

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
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-3">
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="search"
              className="h-8 pl-8 shadow-none"
              placeholder={t("users.searchPlaceholder")}
              aria-label={t("users.searchPlaceholder")}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <FilterChips
            label={t("common.role")}
            value={role}
            onChange={(v) => {
              setRole(v);
              setPage(1);
            }}
            options={[
              { value: "all" as const, label: t("documents.groups.allShort"), count: all.length },
              ...ROLES.map((r) => ({ value: r, label: t(`roles.${r}`), count: all.filter((u) => u.role === r).length })),
            ]}
          />
        </div>
        {users.isLoading && <Skeleton className="m-4 h-40" />}
        {users.data && list.length === 0 && <EmptyState icon={<Search />} title={filtered ? t("common.noMatch") : t("common.empty")} />}
        {list.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="px-4 py-2 font-medium">{t("common.name")}</th>
                  <th className="w-44 px-3 py-2 font-medium">{t("common.role")}</th>
                  <th className="px-3 py-2 font-medium">{t("users.provider")}</th>
                  <th className="px-3 py-2 font-medium">{t("users.status")}</th>
                  <th className="whitespace-nowrap px-3 py-2 font-medium">{t("users.lastLogin")}</th>
                  <th className="w-12" />
                </tr>
              </thead>
              <tbody>
                {paged.items.map((u) => {
                  const self = u.id === me?.id;
                  return (
                    <tr key={u.id} className="border-b border-border last:border-b-0 hover:bg-accent/40">
                      <td className="px-4 py-2.5">
                        <p className={cn("font-medium", !u.active && "text-muted-foreground")}>
                          {u.name || u.email}
                          {self && <span className="ml-2 text-xs font-normal text-muted-foreground">({t("users.you")})</span>}
                        </p>
                        {u.name && <p className="text-xs text-muted-foreground">{u.email}</p>}
                      </td>
                      <td className="px-3 py-2">
                        {self ? (
                          <span className="px-2">{t(`roles.${u.role}`)}</span>
                        ) : (
                          <Select
                            aria-label={t("common.role")}
                            className="h-8 w-36 border-transparent bg-transparent px-2 shadow-none hover:border-input"
                            value={u.role}
                            onValueChange={(v) => patch(u, { role: v as Role })}
                            options={ROLES.map((r) => ({ value: r, label: t(`roles.${r}`) }))}
                          />
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-muted-foreground">
                        {t(`users.providers.${u.provider}`, { defaultValue: u.provider })}
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="flex items-center gap-2 whitespace-nowrap">
                          <span
                            className={cn("size-2 rounded-full", u.active ? "bg-success" : "bg-muted-foreground/50")}
                            aria-hidden
                          />
                          {u.active ? t("users.activeState") : t("users.inactiveState")}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-xs text-muted-foreground">
                        {u.last_login_at ? fmtRelative(u.last_login_at) : t("users.never")}
                      </td>
                      <td className="px-2 py-2.5 text-right">
                        {!self && <RowMenu u={u} onActive={setActive} onDelete={setToDelete} />}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <Pagination page={paged.page} size={USERS_PAGE} total={paged.total} onPage={setPage} />
        {/* Ý nghĩa các quyền: chú thích ở cuối, không chiếm chỗ đầu trang */}
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 border-t border-border bg-muted/30 px-4 py-3 text-xs sm:grid-cols-3">
          {ROLES.map((r) => (
            <div key={r}>
              <dt className="font-medium">{t(`roles.${r}`)}</dt>
              <dd className="text-muted-foreground">{t(`roles.${r}Desc`)}</dd>
            </div>
          ))}
        </dl>
      </div>
      <AddUserDialog open={open} onOpenChange={setOpen} />
      <ConfirmDialog
        open={!!toDisable}
        onOpenChange={(o) => !o && setToDisable(null)}
        title={toDisable ? t("users.deactivateTitle", { email: toDisable.email }) : ""}
        description={t("users.deactivateDesc")}
        confirmLabel={t("users.deactivate")}
        onConfirm={async () => {
          if (toDisable) await patch(toDisable, { active: false });
        }}
      />
      <ConfirmDialog
        open={!!toDelete}
        onOpenChange={(o) => !o && setToDelete(null)}
        title={t("common.delete")}
        description={toDelete ? t("users.deleteConfirm", { email: toDelete.email }) : ""}
        danger
        confirmLabel={t("common.delete")}
        onConfirm={async () => {
          try {
            await api.del(`/users/${toDelete!.id}`);
            toast.success(t("common.saved"));
            qc.invalidateQueries({ queryKey: ["users"] });
          } catch (e) {
            toastError(e);
          }
        }}
      />
    </>
  );
}
