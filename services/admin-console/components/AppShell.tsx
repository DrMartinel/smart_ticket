"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { VIEWS, useViewCounts } from "@/lib/views";
import NotificationBell from "./NotificationBell";

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  const search = useSearchParams();
  const { user, logout } = useAuth();
  const counts = useViewCounts(!!user);

  if (pathname === "/login" || !user) return <>{children}</>;

  const onTickets = pathname.startsWith("/tickets");
  const isManager = user.role === "manager";
  const isWorkflowAdmin = user.capabilities?.includes("workflow_admin") ?? false;
  const currentView = search.get("view") ?? "review";

  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 flex h-dvh w-60 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface)]">
        <div className="flex items-start justify-between gap-2 pb-4 pl-5 pr-3 pt-5">
          <Link href="/tickets?view=review">
            <span className="block text-[15px] font-semibold">Smart Ticket</span>
            <span className="block text-xs text-[var(--text-muted)]">Support console</span>
          </Link>
          <NotificationBell />
        </div>

        <nav className="flex-1 overflow-y-auto px-3 text-sm">
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
          </Group>
          {user.role !== "security" && (
            <Group label="Insights">
              <NavItem href="/dashboard" active={pathname.startsWith("/dashboard")}>
                Dashboard
              </NavItem>
            </Group>
          )}
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
              <NavItem href="/security/access-log" active={pathname.startsWith("/security/access-log")}>
                PII access log
              </NavItem>
            </Group>
          )}
          {(isManager || isWorkflowAdmin) && (
            <Group label="Settings">
              {isManager && (
                <>
                  <NavItem href="/settings/workflows" active={pathname.startsWith("/settings/workflows")}>
                    Workflows
                  </NavItem>
                  <NavItem href="/settings/stages" active={pathname.startsWith("/settings/stages")}>
                    Stages
                  </NavItem>
                </>
              )}
              <NavItem href="/settings/sla" active={pathname === "/settings/sla"}>
                SLA policies
              </NavItem>
              <NavItem href="/settings/sla/calendars" active={pathname.startsWith("/settings/sla/calendars")}>
                Calendars
              </NavItem>
              <NavItem href="/settings/sla/holidays" active={pathname.startsWith("/settings/sla/holidays")}>
                Holidays
              </NavItem>
              <NavItem href="/settings/teams" active={pathname.startsWith("/settings/teams")}>
                Teams
              </NavItem>
              <NavItem href="/settings/notifications" active={pathname.startsWith("/settings/notifications")}>
                Notifications
              </NavItem>
              <NavItem href="/settings/deliveries" active={pathname.startsWith("/settings/deliveries")}>
                Delivery log
              </NavItem>
              {isWorkflowAdmin && (
                <NavItem href="/settings/webhooks" active={pathname.startsWith("/settings/webhooks")}>
                  Webhooks
                </NavItem>
              )}
            </Group>
          )}
        </nav>

        <div className="border-t border-[var(--border)] px-5 py-4 text-sm">
          <p className="font-medium">{user.username}</p>
          <p className="text-xs capitalize text-[var(--text-muted)]">{user.role}</p>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[var(--text-muted)]">
            <Link href="/me/notifications" className="hover:text-[var(--text)]">
              My notifications
            </Link>
            {user.role !== "employee" && (
              <Link href="/me/availability" className="hover:text-[var(--text)]">
                Availability
              </Link>
            )}
            <button onClick={() => void logout()} className="hover:text-[var(--text)]">
              Sign out
            </button>
          </div>
        </div>
      </aside>

      <main className="min-w-0 flex-1 px-8 py-7">{children}</main>
    </div>
  );
}

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mb-5">
      <p className="px-2 pb-1.5 text-[11px] font-medium uppercase tracking-wider text-[var(--text-muted)]">{label}</p>
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
        className={`flex items-center justify-between rounded-[5px] px-2 py-1.5 transition-colors ${
          active ? "bg-[var(--accent-soft)] font-medium text-[var(--accent)]" : "hover:bg-[var(--surface-2)]"
        }`}
      >
        {children}
        {count !== undefined && (
          <span
            className={`font-mono text-xs tabular-nums ${
              emphasise && count > 0 ? "rounded-[3px] bg-[var(--warn-soft)] px-1.5 text-[var(--warn)]" : "text-[var(--text-muted)]"
            }`}
          >
            {count}
          </span>
        )}
      </Link>
    </li>
  );
}
