"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { VIEWS, useViewCounts } from "@/lib/views";

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  const search = useSearchParams();
  const { user, logout } = useAuth();
  const counts = useViewCounts(!!user);

  if (pathname === "/login" || !user) return <>{children}</>;

  const onTickets = pathname.startsWith("/tickets");
  const currentView = search.get("view") ?? "review";

  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 flex h-dvh w-60 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface)]">
        <Link href="/tickets?view=review" className="px-5 pb-4 pt-5">
          <span className="block text-[15px] font-semibold">Smart Ticket</span>
          <span className="block text-xs text-[var(--text-muted)]">Support console</span>
        </Link>

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
          </Group>
          <Group label="Insights">
            <NavItem href="/dashboard" active={pathname.startsWith("/dashboard")}>
              Dashboard
            </NavItem>
          </Group>
          <Group label="Knowledge">
            <NavItem href="/kb" active={pathname.startsWith("/kb")}>
              Help pages
            </NavItem>
          </Group>
          {user.role === "manager" && (
            <Group label="Settings">
              <NavItem href="/settings/workflows" active={pathname.startsWith("/settings/workflows")}>
                Workflows
              </NavItem>
              <NavItem href="/settings/stages" active={pathname.startsWith("/settings/stages")}>
                Stages
              </NavItem>
            </Group>
          )}
        </nav>

        <div className="border-t border-[var(--border)] px-5 py-4 text-sm">
          <p className="font-medium">{user.username}</p>
          <p className="text-xs capitalize text-[var(--text-muted)]">{user.role}</p>
          <button onClick={() => void logout()} className="mt-2 text-xs text-[var(--text-muted)] hover:text-[var(--text)]">
            Sign out
          </button>
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
