"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { adminGroups, areaOf, isActive } from "@/lib/areas";
import { VIEWS, useViewCounts } from "@/lib/views";
import NotificationBell from "./NotificationBell";

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  const search = useSearchParams();
  const { user, logout } = useAuth();
  const counts = useViewCounts(!!user);

  if (pathname === "/login" || !user) return <>{children}</>;

  const area = areaOf(pathname);
  const admin = adminGroups(user);
  const onTickets = pathname.startsWith("/tickets");
  const isManager = user.role === "manager";
  const currentView = search.get("view") ?? "review";

  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 flex h-dvh w-60 shrink-0 flex-col border-r border-border bg-card">
        <div className="flex items-start justify-between gap-2 pb-3 pl-5 pr-3 pt-5">
          <Link href={area === "admin" ? "/admin" : "/tickets?view=review"}>
            <span className="block text-[15px] font-semibold">Smart Ticket</span>
            <span className="block text-xs text-muted-foreground">Support console</span>
          </Link>
          <NotificationBell />
        </div>

        {admin.length > 0 && (
          <div className="mx-3 mb-4 grid grid-cols-2 rounded-md bg-muted p-0.5 text-xs" data-tour="area-switch">
            <AreaTab href="/tickets?view=review" active={area === "workspace"}>
              Workspace
            </AreaTab>
            <AreaTab href="/admin" active={area === "admin"}>
              Admin
            </AreaTab>
          </div>
        )}

        <nav className="scrollbar-none flex-1 overflow-y-auto px-3 text-sm">
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
                    active={onTickets && !pathname.startsWith("/tickets/") && currentView === v.key}
                    count={counts?.[v.key]}
                    emphasise={v.key === "review"}
                  >
                    {v.label}
                  </NavItem>
                ))}
                {user.role !== "security" && (
                  <NavItem href="/board" active={pathname.startsWith("/board")}>
                    Board
                  </NavItem>
                )}
                {user.role !== "employee" && (
                  <NavItem href="/sla" active={pathname === "/sla"}>
                    SLA at risk
                  </NavItem>
                )}
                {user.role !== "employee" && (
                  <NavItem href="/incidents" active={pathname.startsWith("/incidents")}>
                    Sự cố · Incidents
                  </NavItem>
                )}
              </Group>
              {user.role !== "employee" && ((user.teams ?? []).length > 0 || isManager) && (
                <Group label="Teams">
                  {(user.teams ?? []).map((t) => (
                    <NavItem key={t.team} href={`/teams/${t.team}`} active={pathname === `/teams/${t.team}` || pathname.startsWith(`/teams/${t.team}/`)}>
                      {t.team}
                      {t.role === "lead" ? " · lead" : ""}
                    </NavItem>
                  ))}
                  {isManager && (user.teams ?? []).length === 0 && (
                    <NavItem href="/teams" active={pathname.startsWith("/teams")}>
                      All teams
                    </NavItem>
                  )}
                </Group>
              )}
              <Group label="Knowledge">
                <NavItem href="/kb" active={pathname.startsWith("/kb")}>
                  Help pages
                </NavItem>
              </Group>
              {user.role === "security" && (
                <Group label="Security">
                  <NavItem href="/security/alerts" active={pathname.startsWith("/security/alerts")}>
                    Alerts
                  </NavItem>
                  <NavItem href="/security/access-log" active={pathname.startsWith("/security/access-log")}>
                    PII access log
                  </NavItem>
                </Group>
              )}
            </>
          )}
        </nav>

        <div className="border-t border-border px-5 py-4 text-sm" data-tour="account">
          <p className="font-medium">{user.username}</p>
          <p className="text-xs capitalize text-muted-foreground">{user.role}</p>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <Link href="/guides" className="hover:text-foreground" data-tour="guides-link">
              Hướng dẫn · Guides
            </Link>
            <Link href="/me/notifications" className="hover:text-foreground">
              My notifications
            </Link>
            {user.role !== "employee" && (
              <Link href="/me/availability" className="hover:text-foreground">
                Availability
              </Link>
            )}
            <button onClick={() => void logout()} className="hover:text-foreground">
              Sign out
            </button>
          </div>
        </div>
      </aside>

      <main className="min-w-0 flex-1 px-8 py-7">{children}</main>
    </div>
  );
}

function AreaTab({ href, active, children }: { href: string; active: boolean; children: ReactNode }) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`rounded-[5px] py-1 text-center transition-colors ${
        active ? "bg-card font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </Link>
  );
}

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mb-5" data-tour={`nav-${label.toLowerCase()}`}>
      <p className="px-2 pb-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
      <ul className="flex flex-col gap-0.5">{children}</ul>
    </div>
  );
}

function NavItem({
  href,
  active,
  count,
  emphasise = false,
  children,
}: {
  href: string;
  active: boolean;
  count?: number;
  emphasise?: boolean;
  children: ReactNode;
}) {
  return (
    <li>
      <Link
        href={href}
        aria-current={active ? "page" : undefined}
        className={`flex items-center justify-between rounded-md px-2 py-1.5 transition-colors ${
          active ? "bg-primary-soft font-medium text-primary" : "hover:bg-muted"
        }`}
      >
        {children}
        {count !== undefined && (
          <span
            className={`font-mono text-xs tabular-nums ${
              emphasise && count > 0 ? "rounded-[3px] bg-warn-soft px-1.5 text-warn" : "text-muted-foreground"
            }`}
          >
            {count}
          </span>
        )}
      </Link>
    </li>
  );
}
