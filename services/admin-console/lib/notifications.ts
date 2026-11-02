"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { InboxOut, NotificationOut } from "./types/generated";

const FIRST_POLL_SEC = 15;

/** The unread count, polled every `poll_sec` the API hands out while the tab is visible (FR-F4-009). */
export function useUnreadCount(enabled: boolean): { unread: number; refresh: () => void } {
  const [unread, setUnread] = useState(0);
  const pollSec = useRef(FIRST_POLL_SEC);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let busy = false;
    const load = async (always = false) => {
      if (busy) return;
      busy = true;
      clearTimeout(timer);
      if (always || !document.hidden) {
        try {
          const inbox = await api.get<InboxOut>("/api/notifications?unread=true&limit=1");
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
  }, [enabled, tick]);

  return { unread, refresh: useCallback(() => setTick((t) => t + 1), []) };
}

export const notificationsApi = {
  recent: (limit = 10) => api.get<InboxOut>(`/api/notifications?limit=${limit}`),
  read: (id: string) => api.post<void>(`/api/notifications/${encodeURIComponent(id)}/read`),
  readAll: () => api.post<void>("/api/notifications/read-all"),
};

export type Notice = NotificationOut;

/** "9+" over nine, nothing at zero. */
export function badgeCount(unread: number): string | null {
  if (unread <= 0) return null;
  return unread > 9 ? "9+" : String(unread);
}
