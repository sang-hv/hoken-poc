import {
  FileText,
  Gauge,
  KeyRound,
  Languages,
  ListChecks,
  LogOut,
  Menu,
  Moon,
  ScrollText,
  Search,
  Settings,
  Sun,
  Users,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { LANGS } from "@/i18n";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { ChangePasswordDialog } from "@/pages/Users";
import {
  Badge,
  Button,
  Dropdown,
  DropdownContent,
  DropdownItem,
  DropdownLabel,
  DropdownSeparator,
  DropdownTrigger,
} from "./ui";

function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("hoken.theme", dark ? "dark" : "light");
    } catch {
      /* bỏ qua */
    }
  }, [dark]);
  return { dark, toggle: () => setDark((d) => !d) };
}

function NavItem({ to, icon, label, end }: { to: string; icon: React.ReactNode; label: string; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition [&_svg]:size-[18px]",
          isActive
            ? "bg-primary-soft text-primary"
            : "text-muted-foreground hover:bg-accent hover:text-foreground",
        )
      }
    >
      {icon}
      {label}
    </NavLink>
  );
}

export function AppShell() {
  const { t, i18n } = useTranslation();
  const { user, can, logout } = useAuth();
  const theme = useTheme();
  const [open, setOpen] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  const fullBleed = /\/documents\/[^/]+\/(pages|chunks)/.test(loc.pathname);

  const nav = (
    <nav className="flex h-full flex-col gap-1 p-3">
      <div className="mb-4 flex items-center gap-2.5 px-2 pt-1">
        <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
          <svg viewBox="0 0 32 32" className="size-5">
            <path d="M9 16h14M16 9v14" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" />
          </svg>
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{t("app.name")}</p>
          <p className="truncate text-[11px] text-muted-foreground">{t("app.tagline")}</p>
        </div>
      </div>
      <p className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
        {t("nav.sectionWork")}
      </p>
      <NavItem to="/" end icon={<Gauge />} label={t("nav.dashboard")} />
      <NavItem to="/documents" icon={<FileText />} label={t("nav.documents")} />
      <NavItem to="/jobs" icon={<ListChecks />} label={t("nav.jobs")} />
      {can("reviewer") && <NavItem to="/search" icon={<Search />} label={t("nav.search")} />}
      {can("admin") && (
        <>
          <p className="px-3 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
            {t("nav.sectionAdmin")}
          </p>
          <NavItem to="/settings" icon={<Settings />} label={t("nav.settings")} />
          <NavItem to="/users" icon={<Users />} label={t("nav.users")} />
          <NavItem to="/audit" icon={<ScrollText />} label={t("nav.audit")} />
        </>
      )}
    </nav>
  );

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 border-r border-border bg-sidebar lg:block">{nav}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-black/30" />
          <aside className="absolute inset-y-0 left-0 w-64 bg-sidebar shadow-xl" onClick={(e) => e.stopPropagation()}>
            {nav}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-card/70 px-4 backdrop-blur lg:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setOpen(true)} aria-label="menu">
            <Menu />
          </Button>
          <div className="flex-1" />
          <Dropdown>
            <DropdownTrigger asChild>
              <Button variant="ghost" size="sm" aria-label={t("common.language")}>
                <Languages />
                {LANGS.find((l) => l.code === i18n.language)?.label}
              </Button>
            </DropdownTrigger>
            <DropdownContent>
              {LANGS.map((l) => (
                <DropdownItem key={l.code} onSelect={() => i18n.changeLanguage(l.code)}>
                  {l.label}
                </DropdownItem>
              ))}
            </DropdownContent>
          </Dropdown>
          <Button
            variant="ghost"
            size="icon"
            onClick={theme.toggle}
            aria-label={theme.dark ? t("common.themeLight") : t("common.themeDark")}
          >
            {theme.dark ? <Sun /> : <Moon />}
          </Button>
          <Dropdown>
            <DropdownTrigger asChild>
              <button className="flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-accent">
                <span className="flex size-8 items-center justify-center rounded-full bg-primary-soft text-sm font-semibold text-primary">
                  {(user?.name || user?.email || "?").slice(0, 1).toUpperCase()}
                </span>
                <span className="hidden text-left sm:block">
                  <span className="block max-w-40 truncate text-sm font-medium">{user?.name || user?.email}</span>
                  <span className="block text-[11px] text-muted-foreground">{user && t(`roles.${user.role}`)}</span>
                </span>
              </button>
            </DropdownTrigger>
            <DropdownContent>
              <DropdownLabel>
                {user?.email} <Badge className="ml-1">{user && t(`roles.${user.role}`)}</Badge>
              </DropdownLabel>
              <DropdownSeparator />
              {user?.provider === "local" && (
                <DropdownItem onSelect={() => setPwOpen(true)}>
                  <KeyRound />
                  {t("common.changePassword")}
                </DropdownItem>
              )}
              <DropdownItem onSelect={() => logout()}>
                <LogOut />
                {t("common.logout")}
              </DropdownItem>
            </DropdownContent>
          </Dropdown>
        </header>
        <main className={cn("min-h-0 flex-1 overflow-y-auto", !fullBleed && "px-4 py-6 lg:px-8")}>
          <div className={cn(!fullBleed && "mx-auto max-w-7xl", fullBleed && "h-full")}>
            <Outlet />
          </div>
        </main>
      </div>
      <ChangePasswordDialog open={pwOpen} onOpenChange={setPwOpen} />
    </div>
  );
}
