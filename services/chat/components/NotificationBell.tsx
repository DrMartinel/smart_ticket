"use client";

// The bell and its panel in the chat header (F4 · Notification bell 11-480, panel 11-531).

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { notificationsApi } from "@/lib/api";
import type { NotificationOut } from "@/lib/types/generated";

const FIRST_POLL_SEC = 15;

function noticeTime(iso: string): string {
  const at = new Date(iso);
  const zone = "Asia/Ho_Chi_Minh";
  const day = (d: Date) => d.toLocaleDateString("vi-VN", { timeZone: zone });
  const time = at.toLocaleTimeString("vi-VN", { timeZone: zone, hour: "2-digit", minute: "2-digit" });
  return day(at) === day(new Date()) ? time : `${day(at)} ${time}`;
}

export default function NotificationBell() {
  const router = useRouter();
  const [unread, setUnread] = useState(0);
  const [tick, setTick] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationOut[] | null>(null);
  const [error, setError] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const pollSec = useRef(FIRST_POLL_SEC);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let busy = false;
    const load = async (always = false) => {
      if (busy) return;
      busy = true;
      clearTimeout(timer);
      if (always || !document.hidden) {
        try {
          const inbox = await notificationsApi.unread();
          setUnread(inbox.unread);
          pollSec.current = inbox.poll_sec;
        } catch {
          // keep the last count; the next poll tries again
        }
      }
      busy = false;
      if (alive) timer = setTimeout(() => void load(), pollSec.current * 1000);
    };
    const onVisible = () => {
      if (!document.hidden) void load();
    };
    void load(true);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [tick]);

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

  const openNotice = async (notice: NotificationOut) => {
    if (!notice.read_at) await notificationsApi.read(notice.id).catch(() => undefined);
    setTick((t) => t + 1);
    setOpen(false);
    // Opens links into this app only: a requester's notice links to its ticket here.
    const path = chatPath(notice.link);
    if (path) router.push(path);
  };

  const readAll = async () => {
    await notificationsApi.readAll().catch(() => undefined);
    setItems((list) => list?.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })) ?? null);
    setTick((t) => t + 1);
  };

  const count = unread <= 0 ? null : unread > 9 ? "9+" : String(unread);

  return (
    <div ref={panel} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={count ? `Thông báo, ${unread} chưa đọc` : "Thông báo"}
        aria-expanded={open}
        className="flex items-center gap-1 rounded-[5px] p-1 text-[var(--text-muted)] hover:text-[var(--text)]"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
          <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" strokeLinecap="round" />
        </svg>
        {count && (
          <span className="min-w-5 rounded-full bg-[var(--danger-soft)] px-1.5 text-center text-xs font-medium tabular-nums text-[var(--danger)]">
            {count}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Thông báo"
          className="fixed inset-x-3 top-14 z-40 flex max-h-[70dvh] flex-col overflow-hidden rounded-[8px] border border-[var(--border)] bg-[var(--surface)] shadow-lg sm:absolute sm:inset-x-auto sm:right-0 sm:top-9 sm:w-[400px]"
        >
          <header className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
            <h2 className="text-sm font-semibold">Thông báo</h2>
            <button className="text-xs text-[var(--accent)] hover:underline disabled:opacity-50" disabled={!unread} onClick={() => void readAll()}>
              Đánh dấu đã đọc tất cả
            </button>
          </header>
          <ul className="flex-1 overflow-y-auto">
            {error && <li className="px-4 py-6 text-sm text-[var(--danger)]">Không tải được thông báo.</li>}
            {items?.length === 0 && <li className="px-4 py-6 text-center text-sm text-[var(--text-muted)]">Chưa có thông báo nào.</li>}
            {items?.map((notice) => (
              <li key={notice.id} className="border-b border-[var(--border)] last:border-b-0">
                <button
                  onClick={() => void openNotice(notice)}
                  className={`flex w-full flex-col gap-1 px-4 py-3 text-left hover:bg-[var(--surface-2)] ${notice.read_at ? "" : "bg-[var(--accent-soft)]"}`}
                >
                  <span className="text-xs text-[var(--text-muted)]">
                    {noticeTime(notice.created_at)}
                    {!notice.read_at && <span className="sr-only"> · chưa đọc</span>}
                  </span>
                  <span className="text-sm">{notice.subject}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** The in-app path of a notice link into this app, absolute or relative; null for elsewhere. */
function chatPath(link: string): string | null {
  if (link.startsWith("/")) return link;
  try {
    const url = new URL(link);
    return url.origin === window.location.origin ? `${url.pathname}${url.search}` : null;
  } catch {
    return null;
  }
}
