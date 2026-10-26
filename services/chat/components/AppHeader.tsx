"use client";

// The bar above every chat page: the app, My tickets, the bell and the account.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import NotificationBell from "./NotificationBell";

export default function AppHeader() {
  const { user, logout } = useAuth();
  const path = usePathname();
  const onTickets = path.startsWith("/tickets");
  return (
    <header className="border-b border-[var(--border)] bg-[var(--surface)]">
      <div className="flex items-center justify-between gap-3 px-4 py-3 md:px-6">
        <Link href="/" className="flex items-baseline gap-3">
          <span className="font-semibold">IT Help</span>
          <span className="hidden text-sm text-[var(--text-muted)] sm:inline">Answers from approved help pages</span>
        </Link>
        <nav className="flex items-center gap-4 text-sm">
          <Link
            href={onTickets ? "/" : "/tickets"}
            className="text-[var(--accent)] underline-offset-2 hover:underline"
          >
            {onTickets ? "Hỏi đáp · Chat" : "Đơn của tôi · My tickets"}
          </Link>
          <NotificationBell />
          {user && <span className="hidden text-[var(--text-muted)] sm:inline">{user.username}</span>}
          <button onClick={() => void logout()} className="text-[var(--text-muted)] hover:text-[var(--text)]">
            Sign out
          </button>
        </nav>
      </div>
    </header>
  );
}
