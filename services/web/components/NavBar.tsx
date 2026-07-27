"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";

const LINKS = [
  { href: "/submit", label: "Submit" },
  { href: "/queue", label: "Queue" },
  { href: "/dashboard", label: "Dashboard" },
  { href: "/kb", label: "Knowledge Base" },
];

export default function NavBar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  if (pathname === "/login") return null;

  return (
    <header className="border-b" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-6">
          <Link href="/submit" className="font-semibold">
            Smart Ticket Triage
          </Link>
          <nav className="flex gap-4 text-sm">
            {LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                className={pathname?.startsWith(l.href) ? "font-medium text-[var(--accent)]" : "text-[var(--text-muted)]"}
              >
                {l.label}
              </Link>
            ))}
          </nav>
        </div>
        {user && (
          <div className="flex items-center gap-3 text-sm">
            <span className="text-[var(--text-muted)]">
              {user.username} <span className="opacity-70">({user.role})</span>
            </span>
            <button onClick={logout} className="rounded border px-2 py-1 text-xs" style={{ borderColor: "var(--border)" }}>
              Log out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
