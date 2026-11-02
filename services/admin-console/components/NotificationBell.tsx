"use client";

// The bell and its panel (F4 · Notification bell 11-480, Notification panel 11-531).

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { notificationEventClasses } from "@/lib/badges";
import { badgeCount, notificationsApi, useUnreadCount, type Notice } from "@/lib/notifications";

function noticeTime(iso: string): string {
  const at = new Date(iso);
  const zone = "Asia/Ho_Chi_Minh";
  const day = (d: Date) => d.toLocaleDateString("en-GB", { timeZone: zone });
  const time = at.toLocaleTimeString("en-GB", { timeZone: zone, hour: "2-digit", minute: "2-digit" });
  if (day(at) === day(new Date())) return time;
  return `${at.toLocaleDateString("en-GB", { timeZone: zone, weekday: "short" })} ${time}`;
}

export default function NotificationBell() {
  const router = useRouter();
  const { unread, refresh } = useUnreadCount(true);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Notice[] | null>(null);
  const [error, setError] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const count = badgeCount(unread);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setError(false);
    notificationsApi
      .recent()
      .then((inbox) => alive && setItems(inbox.items))
      .catch(() => alive && setError(true));
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !panel.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      alive = false;
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  const openNotice = async (notice: Notice) => {
    if (!notice.read_at) await notificationsApi.read(notice.id).catch(() => undefined);
    refresh();
    setOpen(false);
    if (notice.link) router.push(notice.link);
  };

  const readAll = async () => {
    await notificationsApi.readAll().catch(() => undefined);
    setItems((list) => list?.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })) ?? null);
    refresh();
  };

  return (
    <div ref={panel} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={count ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        className="flex items-center gap-1 rounded-[5px] p-1 text-[var(--text-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--text)]"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
          <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" strokeLinecap="round" />
        </svg>
        {count && (
          <span className="min-w-5 rounded-full bg-[var(--danger-soft)] px-1.5 text-center font-mono text-xs font-medium tabular-nums text-[var(--danger)]">
            {count}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Notifications"
          className="card fixed left-[232px] top-3 z-40 flex max-h-[min(560px,calc(100dvh-24px))] w-[min(440px,calc(100vw-248px))] flex-col overflow-hidden shadow-lg"
        >
          <header className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
            <h2 className="text-sm font-semibold">Thông báo · Notifications</h2>
            <button className="text-xs text-[var(--accent)] hover:underline disabled:opacity-50" disabled={!unread} onClick={() => void readAll()}>
              Mark all read
            </button>
          </header>
          <ul className="flex-1 overflow-y-auto">
            {error && <li className="px-4 py-6 text-sm text-[var(--danger)]">Couldn&apos;t load notifications.</li>}
            {items?.length === 0 && <li className="px-4 py-6 text-center text-sm text-[var(--text-muted)]">Nothing yet.</li>}
            {items?.map((notice) => (
              <li key={notice.id} className="border-b border-[var(--border)] last:border-b-0">
                <button
                  onClick={() => void openNotice(notice)}
                  className={`flex w-full flex-col gap-1 px-4 py-3 text-left hover:bg-[var(--surface-2)] ${notice.read_at ? "" : "bg-[var(--info-soft)]"}`}
                >
                  <span className="flex items-center gap-2">
                    <span className={`badge ${notificationEventClasses(notice.event)}`}>{notice.event}</span>
                    <span className="text-xs text-[var(--text-muted)]">{noticeTime(notice.created_at)}</span>
                    {!notice.read_at && <span className="sr-only">unread</span>}
                  </span>
                  <span className="text-sm">{notice.subject}</span>
                </button>
              </li>
            ))}
          </ul>
          <footer className="border-t border-[var(--border)] px-4 py-2.5">
            <Link href="/me/notifications" onClick={() => setOpen(false)} className="text-xs text-[var(--accent)] hover:underline">
              Notification settings
            </Link>
          </footer>
        </div>
      )}
    </div>
  );
}
