"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import {
  AlarmClock,
  BookOpen,
  CircleHelp,
  Columns3,
  Inbox,
  ListChecks,
  LogOut,
  Menu,
  Bell,
  CalendarClock,
  ShieldAlert,
  Siren,
  Users,
  X,
  type LucideIcon,
  CheckCheck,
  Layers,
  UserRound,
  FileLock2,
  KeyRound,
  ClipboardCheck,
} from "lucide-react";
import { useAuth, type CurrentUser } from "@/lib/auth";
import { adminGroups, areaOf, isActive } from "@/lib/areas";
import { P, can } from "@/lib/permissions";
import { VIEWS, useViewCounts } from "@/lib/views";
import { cn } from "@/lib/utils";
import NotificationBell from "./NotificationBell";

const VIEW_ICON: Record<string, LucideIcon> = {
  review: ListChecks,
  mine: UserRound,
  open: Inbox,
  resolved: CheckCheck,
  all: Layers,
};

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  const search = useSearchParams();
  const { user } = useAuth();
  const counts = useViewCounts(!!user);
  const [drawer, setDrawer] = useState(false);

  useEffect(() => setDrawer(false), [pathname, search]);

  if (pathname === "/login" || !user) return <>{children}</>;

  const area = areaOf(pathname);
  const home = area === "admin" ? "/admin" : "/tickets?view=review";
  const nav = <Navigation user={user} pathname={pathname} view={search.get("view") ?? "review"} counts={counts} />;

  return (
    <div className="flex min-h-dvh flex-col lg:flex-row">
      <a
        href="#main"
        className="sr-only z-[70] rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-40 flex h-14 items-center justify-between gap-2 border-b border-border bg-card/95 px-2 backdrop-blur-sm lg:hidden">
        <button
          type="button"
          onClick={() => setDrawer(true)}
          aria-label="Open navigation"
          className="inline-flex size-11 items-center justify-center rounded-md text-foreground hover:bg-muted"
        >
          <Menu className="size-5" />
        </button>
        <Link href={home} className="min-w-0 flex-1 truncate">
          <Brand />
        </Link>
        <NotificationBell />
      </header>

      <DialogPrimitive.Root open={drawer} onOpenChange={setDrawer}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-[rgb(22_21_19/0.45)] data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0 lg:hidden" />
          <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-50 flex w-[min(300px,86vw)] flex-col bg-card shadow-float duration-200 data-[state=closed]:animate-out data-[state=closed]:slide-out-to-left data-[state=open]:animate-in data-[state=open]:slide-in-from-left lg:hidden">
            <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
            <DialogPrimitive.Description className="sr-only">The console&apos;s pages</DialogPrimitive.Description>
            <div className="flex h-14 items-center justify-between border-b border-border pr-2 pl-5">
              <Brand />
              <DialogPrimitive.Close aria-label="Close navigation" className="inline-flex size-11 items-center justify-center rounded-md hover:bg-muted">
                <X className="size-5" />
              </DialogPrimitive.Close>
            </div>
            {nav}
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>

      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-border bg-card lg:flex">
        <div className="flex h-16 items-center justify-between gap-2 pr-2 pl-5">
          <Link href={home}>
            <Brand />
          </Link>
          <NotificationBell />
        </div>
        {nav}
      </aside>

      <main id="main" tabIndex={-1} className="min-w-0 flex-1 px-4 py-5 outline-none sm:px-6 sm:py-6 lg:px-8 lg:py-7">
        {children}
      </main>
    </div>
  );
}

function Brand() {
  return (
    <span className="flex items-center gap-2.5">
      <span aria-hidden className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary font-display text-sm font-semibold text-primary-foreground">
        S
      </span>
      <span className="min-w-0 leading-tight">
        <span className="block truncate text-sm font-semibold">Smart Ticket</span>
        <span className="eyebrow block !text-[10px] !leading-3">Support console</span>
      </span>
    </span>
  );
}

function Navigation({
  user,
  pathname,
  view,
  counts,
}: {
  user: CurrentUser;
  pathname: string;
  view: string;
  counts: Record<string, number> | null;
}) {
  const { logout } = useAuth();
  const area = areaOf(pathname);
  const admin = adminGroups(user);
  const onTickets = pathname.startsWith("/tickets");
  const isManager = user.role === "manager";

  return (
    <>
      {admin.length > 0 && (
        <div className="mx-3 mt-3 mb-4 grid grid-cols-2 rounded-md bg-muted p-0.5 text-xs lg:mt-0" data-tour="area-switch">
          <AreaTab href="/tickets?view=review" active={area === "workspace"}>
            Workspace
          </AreaTab>
          <AreaTab href="/admin" active={area === "admin"}>
            Admin
          </AreaTab>
        </div>
      )}

      <nav aria-label="Main" className="scrollbar-none flex-1 overflow-y-auto px-3 pt-1 text-sm">
        {area === "admin" ? (
          admin.map((g) => (
            <Group key={g.label} label={g.label}>
              {g.links.map((l) => (
                <NavItem key={l.href} href={l.href} active={isActive(l, pathname)}>
                  {l.label}
                </NavItem>
              ))}
            </Group>
          ))
        ) : (
          <>
            <Group label="Tickets">
              {VIEWS.map((v) => (
                <NavItem
                  key={v.key}
                  href={`/tickets?view=${v.key}`}
                  icon={VIEW_ICON[v.key]}
                  active={onTickets && !pathname.startsWith("/tickets/") && view === v.key}
                  count={counts?.[v.key]}
                  emphasise={v.key === "review"}
                >
                  {v.label}
                </NavItem>
              ))}
              {user.role !== "security" && (
                <NavItem href="/board" icon={Columns3} active={pathname.startsWith("/board")}>
                  Board
                </NavItem>
              )}
              {user.role !== "employee" && (
                <NavItem href="/sla" icon={AlarmClock} active={pathname === "/sla"}>
                  SLA at risk
                </NavItem>
              )}
              {user.role !== "employee" && (
                <NavItem href="/incidents" icon={Siren} active={pathname.startsWith("/incidents")}>
                  Incidents
                </NavItem>
              )}
            </Group>
            {user.role !== "employee" && ((user.teams ?? []).length > 0 || isManager) && (
              <Group label="Teams">
                {(user.teams ?? []).map((t) => (
                  <NavItem
                    key={t.team}
                    href={`/teams/${t.team}`}
                    icon={Users}
                    active={pathname === `/teams/${t.team}` || pathname.startsWith(`/teams/${t.team}/`)}
                  >
                    {t.team}
                    {t.role === "lead" && <span className="ml-1.5 text-xs font-normal text-muted-foreground">lead</span>}
                  </NavItem>
                ))}
                {isManager && (user.teams ?? []).length === 0 && (
                  <NavItem href="/teams" icon={Users} active={pathname.startsWith("/teams")}>
                    All teams
                  </NavItem>
                )}
              </Group>
            )}
            <Group label="Knowledge">
              <NavItem href="/kb" icon={BookOpen} active={pathname.startsWith("/kb")}>
                Help pages
              </NavItem>
            </Group>
            {user.role === "security" && (
              <Group label="Security">
                <NavItem href="/security/alerts" icon={ShieldAlert} active={pathname.startsWith("/security/alerts")}>
                  Alerts
                </NavItem>
                <NavItem href="/security/access-log" icon={FileLock2} active={pathname.startsWith("/security/access-log")}>
                  PII access log
                </NavItem>
              </Group>
            )}
          </>
        )}
      </nav>

      <div className="border-t border-border px-3 py-3 text-sm" data-tour="account">
        <div className="flex items-center gap-2.5 px-2 pb-2">
          <span aria-hidden className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted font-mono text-xs font-medium uppercase">
            {user.username.slice(0, 2)}
          </span>
          <span className="min-w-0">
            <span className="block truncate font-medium">{user.username}</span>
            <span className="block text-xs capitalize text-muted-foreground">{user.role}</span>
          </span>
        </div>
        <ul className="flex flex-col gap-0.5 text-[13px]">
          <NavItem href="/guides" icon={CircleHelp} active={pathname === "/guides"} quiet tour="guides-link">
            Guides
          </NavItem>
          <NavItem href="/me/notifications" icon={Bell} active={pathname === "/me/notifications"} quiet>
            My notifications
          </NavItem>
          {user.role !== "employee" && (
            <NavItem href="/me/availability" icon={CalendarClock} active={pathname === "/me/availability"} quiet>
              My availability
            </NavItem>
          )}
          <NavItem href="/me/access" icon={KeyRound} active={pathname === "/me/access"} quiet>
            My access
          </NavItem>
          {can(user, P.reviewRespond) && (
            <NavItem href="/me/access-reviews" icon={ClipboardCheck} active={pathname === "/me/access-reviews"} quiet>
              Access reviews
            </NavItem>
          )}
          <li>
            <button
              data-slot="nav-item"
              onClick={() => void logout()}
              className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground"
            >
              <LogOut className="size-4" aria-hidden />
              Sign out
            </button>
          </li>
        </ul>
      </div>
    </>
  );
}

function AreaTab({ href, active, children }: { href: string; active: boolean; children: ReactNode }) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex min-h-8 items-center justify-center rounded-[5px] text-center transition-colors duration-150",
        active ? "bg-card font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </Link>
  );
}

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mb-5" data-tour={`nav-${label.toLowerCase()}`}>
      <p className="eyebrow px-2 pb-1.5">{label}</p>
      <ul className="flex flex-col gap-0.5">{children}</ul>
    </div>
  );
}

function NavItem({
  href,
  active,
  count,
  icon: Icon,
  emphasise = false,
  quiet = false,
  tour,
  children,
}: {
  href: string;
  active: boolean;
  count?: number;
  icon?: LucideIcon;
  emphasise?: boolean;
  quiet?: boolean;
  tour?: string;
  children: ReactNode;
}) {
  return (
    <li>
      <Link
        href={href}
        data-slot="nav-item"
        data-tour={tour}
        aria-current={active ? "page" : undefined}
        className={cn(
          "relative flex items-center gap-2.5 rounded-md px-2 py-1.5 transition-colors duration-150",
          active
            ? "bg-primary-soft font-medium text-primary before:absolute before:inset-y-1.5 before:-left-3 before:w-0.5 before:rounded-r before:bg-primary"
            : quiet
              ? "text-muted-foreground hover:bg-muted hover:text-foreground"
              : "hover:bg-muted",
        )}
      >
        {Icon && <Icon className={cn("size-4 shrink-0", active ? "text-primary" : "text-muted-foreground")} aria-hidden />}
        <span className="min-w-0 flex-1 truncate">{children}</span>
        {count !== undefined && (
          <span
            className={cn(
              "num rounded-sm px-1.5 text-xs",
              emphasise && count > 0 ? "bg-warn-soft font-medium text-warn" : "text-muted-foreground",
            )}
          >
            {count}
          </span>
        )}
      </Link>
    </li>
  );
}
