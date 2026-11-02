"use client";

// The bell and its panel (F4 · Notification bell 11-480, Notification panel 11-531).

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { BellIcon } from "lucide-react";
import { notificationEventTone } from "@/lib/badges";
import { badgeCount, notificationsApi, useUnreadCount, type Notice } from "@/lib/notifications";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

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
  const count = badgeCount(unread);

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
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          aria-label={count ? `Notifications, ${unread} unread` : "Notifications"}
          className="gap-1 px-1.5 text-muted-foreground hover:text-foreground"
        >
          <BellIcon className="size-[18px]" aria-hidden />
          {count && (
            <span className="min-w-5 rounded-full bg-danger-soft px-1.5 text-center font-mono text-xs font-medium tabular-nums text-danger">
              {count}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="start"
        collisionPadding={12}
        aria-label="Notifications"
        className="flex max-h-[min(560px,calc(100dvh-24px))] w-[min(440px,calc(100vw-248px))] flex-col overflow-hidden p-0"
      >
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">Thông báo · Notifications</h2>
          <Button variant="link" size="inline" className="text-xs disabled:opacity-50" disabled={!unread} onClick={() => void readAll()}>
            Mark all read
          </Button>
        </header>
        <ul className="flex-1 overflow-y-auto">
          {error && <li className="px-4 py-6 text-sm text-danger">Couldn&apos;t load notifications.</li>}
          {items?.length === 0 && <li className="px-4 py-6 text-center text-sm text-muted-foreground">Nothing yet.</li>}
          {items?.map((notice) => (
            <li key={notice.id} className="border-b border-border last:border-b-0">
              <button
                onClick={() => void openNotice(notice)}
                className={`flex w-full flex-col gap-1 px-4 py-3 text-left hover:bg-muted ${notice.read_at ? "" : "bg-info-soft"}`}
              >
                <span className="flex items-center gap-2">
                  <Badge variant={notificationEventTone(notice.event)}>{notice.event}</Badge>
                  <span className="text-xs text-muted-foreground">{noticeTime(notice.created_at)}</span>
                  {!notice.read_at && <span className="sr-only">unread</span>}
                </span>
                <span className="text-sm">{notice.subject}</span>
              </button>
            </li>
          ))}
        </ul>
        <footer className="border-t border-border px-4 py-2.5">
          <Link href="/me/notifications" onClick={() => setOpen(false)} className="text-xs text-primary hover:underline">
            Notification settings
          </Link>
        </footer>
      </PopoverContent>
    </Popover>
  );
}
