"use client";

// The severity and state chips of the security inbox (F8).

import { Badge, type Tone } from "@/components/ui/badge";

const SEVERITY: Record<string, Tone> = {
  critical: "danger",
  high: "warn",
  medium: "neutral",
};

const STATE: Record<string, Tone> = {
  new: "brand",
  acknowledged: "ok",
  investigating: "warn",
  closed: "neutral",
};

export function SeverityChip({ severity }: { severity: string }) {
  return <Badge variant={SEVERITY[severity] ?? "neutral"}>{severity}</Badge>;
}

export function StateChip({ state, resolution }: { state: string; resolution?: string | null }) {
  return (
    <Badge variant={STATE[state] ?? "neutral"}>
      {state}
      {resolution ? ` · ${resolution}` : ""}
    </Badge>
  );
}

export function vnTime(iso: string): string {
  const date = new Date(iso);
  const today = new Date().toDateString() === date.toDateString();
  return date.toLocaleString("en-GB", {
    timeZone: "Asia/Ho_Chi_Minh",
    ...(today ? {} : { weekday: "short", day: "numeric", month: "short" }),
    hour: "2-digit",
    minute: "2-digit",
  });
}
