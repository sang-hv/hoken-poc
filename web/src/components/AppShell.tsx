import {
  FileText,
  Gauge,
  KeyRound,
  Languages,
  LogOut,
  Menu,
  MessagesSquare,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  Settings,
  Sun,
  Users,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation, useMatch, useResolvedPath } from "react-router-dom";
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
  Tip,
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

function NavItem({
  to,
  icon,
  label,
  end,
  collapsed,
  also,
}: {
  to: string;
  icon: React.ReactNode;
  label: string;
  end?: boolean;
  collapsed?: boolean;
  /** Đường dẫn khác cũng tính là đang ở mục này. */
  also?: RegExp;
}) {
  const loc = useLocation();
  // Tự tính active và truyền className dạng CHUỖI: khi thu gọn, Tooltip (Radix Slot) gộp className kiểu chuỗi —
  // className dạng hàm của NavLink sẽ bị mất (icon lệch, không có nền active).
  const resolved = useResolvedPath(to);
  const matched = !!useMatch({ path: resolved.pathname, end: !!end });
  const active = matched || (!!also && also.test(loc.pathname));
  const link = (
    <NavLink
      to={to}
      end={end}
      aria-label={collapsed ? label : undefined}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-3 rounded-lg py-2 text-sm font-medium transition [&_svg]:size-[18px] [&_svg]:shrink-0",
        collapsed ? "mx-auto size-10 justify-center px-0" : "px-3",
        active ? "bg-primary-soft text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      {icon}
      {!collapsed && <span className="truncate">{label}</span>}
    </NavLink>
  );
  // Thu gọn: chỉ còn icon, tên hiện ở tooltip bên phải
  return collapsed ? (
    <Tip content={label} side="right">
      {link}
    </Tip>
  ) : (
    link
  );
}

function NavSection({ label, collapsed }: { label: string; collapsed: boolean }) {
  return collapsed ? (
    <div className="mx-2 my-2 border-t border-border" role="separator" aria-label={label} />
  ) : (
    <p className="px-3 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80 first-of-type:pt-2">
      {label}
    </p>
  );
}

/** Trạng thái thu gọn sidebar (desktop), nhớ theo trình duyệt. */
function useSidebarCollapsed() {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem("hoken.sidebar") === "collapsed";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem("hoken.sidebar", collapsed ? "collapsed" : "expanded");
    } catch {
      /* bỏ qua */
    }
  }, [collapsed]);
  return { collapsed, toggle: () => setCollapsed((c) => !c) };
}

/** Màn chi tiết tài liệu / review: toàn màn hình, sidebar thu về dải icon cho đủ rộng. */
const DETAIL_ROUTE = /^\/documents\/[^/]+(\/(pages|chunks)\/?.*)?$/;

export function AppShell() {
  const { t, i18n } = useTranslation();
  const { user, can, logout } = useAuth();
  const theme = useTheme();
  const [open, setOpen] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);
  const stored = useSidebarCollapsed();
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  const onDetail = /^\/documents\/[^/]+$/.test(loc.pathname);
  // Màn chi tiết tài liệu: mặc định thu gọn, vẫn mở được bằng nút; không ghi đè lựa chọn đã lưu cho các màn khác
  const [detailExpanded, setDetailExpanded] = useState(false);
  useEffect(() => {
    if (!onDetail) setDetailExpanded(false);
  }, [onDetail]);
  const sidebar = onDetail ? { collapsed: !detailExpanded, toggle: () => setDetailExpanded((v) => !v) } : stored;
  const fullBleed = DETAIL_ROUTE.test(loc.pathname);

  /** Menu dùng cho sidebar desktop (có thể thu gọn) và ngăn kéo trên mobile (luôn mở rộng). */
  const nav = (collapsed: boolean, collapsible: boolean) => (
    <nav className="flex h-full flex-col gap-1 overflow-y-auto overflow-x-hidden p-3">
      <div className={cn("mb-4 flex items-center gap-2.5 pt-1", collapsed ? "justify-center px-0" : "px-2")}>
        <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
          <svg viewBox="0 0 32 32" className="size-5" aria-hidden>
            <path d="M9 16h14M16 9v14" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" />
          </svg>
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{t("app.name")}</p>
            <p className="truncate text-[11px] text-muted-foreground">{t("app.tagline")}</p>
          </div>
        )}
      </div>
      <NavSection label={t("nav.sectionOps")} collapsed={collapsed} />
      <NavItem to="/dashboard" end icon={<Gauge />} label={t("nav.dashboard")} collapsed={collapsed} />
      <NavItem to="/documents" icon={<FileText />} label={t("nav.documents")} collapsed={collapsed} />
      {can("reviewer") && (
        <>
          <NavSection label={t("nav.sectionTest")} collapsed={collapsed} />
          <NavItem to="/test/chat" icon={<MessagesSquare />} label={t("nav.chat")} collapsed={collapsed} />
        </>
      )}
      {can("admin") && (
        <>
          <NavSection label={t("nav.sectionAdmin")} collapsed={collapsed} />
          <NavItem to="/settings" icon={<Settings />} label={t("nav.settings")} collapsed={collapsed} />
          <NavItem to="/users" icon={<Users />} label={t("nav.users")} collapsed={collapsed} />
          <NavItem to="/audit" icon={<ScrollText />} label={t("nav.audit")} collapsed={collapsed} />
        </>
      )}
      {collapsible && (
        <div className="mt-auto pt-3">
          <Tip content={collapsed ? t("nav.expand") : ""} side="right">
            <Button
              variant="ghost"
              size="sm"
              onClick={sidebar.toggle}
              aria-label={collapsed ? t("nav.expand") : t("nav.collapse")}
              aria-expanded={!collapsed}
              className={cn("w-full text-muted-foreground", collapsed ? "justify-center px-0" : "justify-start")}
            >
              {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
              {!collapsed && t("nav.collapse")}
            </Button>
          </Tip>
        </div>
      )}
    </nav>
  );

  return (
    <div className="flex h-full">
      <aside
        className={cn(
          "hidden shrink-0 border-r border-border bg-sidebar transition-[width] duration-200 lg:block",
          sidebar.collapsed ? "w-16" : "w-60",
        )}
      >
        {nav(sidebar.collapsed, true)}
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-black/30" />
          <aside className="absolute inset-y-0 left-0 w-64 bg-sidebar shadow-xl" onClick={(e) => e.stopPropagation()}>
            {nav(false, false)}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-card/70 px-4 backdrop-blur lg:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setOpen(true)} aria-label={t("nav.openMenu")}>
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
