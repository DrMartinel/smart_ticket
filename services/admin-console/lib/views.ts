"use client";

import { useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { api } from "./api";

export const VIEWS = [
  { key: "review", label: "Needs review" },
  { key: "mine", label: "Assigned to me" },
  { key: "open", label: "Open" },
  { key: "resolved", label: "Resolved" },
  { key: "all", label: "All tickets" },
] as const;

export type ViewKey = (typeof VIEWS)[number]["key"];

/** How many tickets each view holds, refreshed on navigation and every minute. */
export function useViewCounts(enabled: boolean): Record<string, number> | null {
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const pathname = usePathname();
  const search = useSearchParams();

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    const load = () =>
      api
        .get<{ counts: Record<string, number> }>("/api/tickets?limit=1")
        .then((page) => alive && setCounts(page.counts))
        .catch(() => undefined);
    load();
    const timer = setInterval(load, 60_000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [enabled, pathname, search]);

  return counts;
}
