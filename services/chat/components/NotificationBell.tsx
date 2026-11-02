"use client";

// The bell and its panel in the chat header (F4 · Notification bell 11-480, panel 11-531).

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { notificationsApi } from "@/lib/api";
import type { NotificationOut } from "@/lib/types/generated";
import { BellIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

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
    return () => {
      alive = false;
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
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          aria-label={count ? `Thông báo, ${unread} chưa đọc` : "Thông báo"}
          className="gap-1 px-1.5 text-muted-foreground hover:text-foreground"
        >
          <BellIcon className="size-[18px]" aria-hidden />
          {count && (
            <span className="min-w-5 rounded-full bg-danger-soft px-1.5 text-center text-xs font-medium tabular-nums text-danger">
              {count}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        collisionPadding={12}
        aria-label="Thông báo"
        className="flex max-h-[70dvh] w-[min(400px,calc(100vw-24px))] flex-col overflow-hidden p-0"
      >
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">Thông báo</h2>
          <Button variant="link" size="inline" className="text-xs disabled:opacity-50" disabled={!unread} onClick={() => void readAll()}>
            Đánh dấu đã đọc tất cả
          </Button>
        </header>
        <ul className="flex-1 overflow-y-auto">
          {error && <li className="px-4 py-6 text-sm text-danger">Không tải được thông báo.</li>}
          {items?.length === 0 && <li className="px-4 py-6 text-center text-sm text-muted-foreground">Chưa có thông báo nào.</li>}
          {items?.map((notice) => (
            <li key={notice.id} className="border-b border-border last:border-b-0">
              <button
                onClick={() => void openNotice(notice)}
                className={`flex w-full flex-col gap-1 px-4 py-3 text-left hover:bg-muted ${notice.read_at ? "" : "bg-primary-soft"}`}
              >
                <span className="text-xs text-muted-foreground">
                  {noticeTime(notice.created_at)}
                  {!notice.read_at && <span className="sr-only"> · chưa đọc</span>}
                </span>
                <span className="text-sm">{notice.subject}</span>
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
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
