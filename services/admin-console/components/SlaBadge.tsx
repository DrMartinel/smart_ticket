"use client";

// The SLA badge (F1 · SLA badge 8-604): business time left on the response clock until it is met,
// then on the resolution clock; the tooltip lists both.

import { slaLevelTone, ticketPriorityTone } from "@/lib/badges";
import type { SlaBadgeOut } from "@/lib/types/generated";
import { Badge } from "@/components/ui/badge";

/** "35m", "3h 20m", "28h": business minutes in short units. */
export function businessDuration(minutes: number): string {
  const m = Math.abs(Math.round(minutes));
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return h >= 24 || rest === 0 ? `${h}h` : `${h}h ${rest}m`;
}

function vnTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GB", {
    timeZone: "Asia/Ho_Chi_Minh",
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function slaLabel(badge: SlaBadgeOut): string {
  switch (badge.level) {
    case "breached":
      return `Breached ${businessDuration(-badge.remaining_minutes)} ago`;
    case "at_risk":
      return `At risk · ${businessDuration(badge.remaining_minutes)} left`;
    case "paused":
      return "Paused";
    case "met":
      return "Met";
    default:
      return `${businessDuration(badge.remaining_minutes)} left`;
  }
}

function tooltip(badge: SlaBadgeOut): string {
  const lines = badge.clocks.map((c) => {
    const name = c.kind === "response" ? "Response" : "Resolution";
    const when = c.state === "met" ? `met ${vnTime(c.met_at)}` : `due ${vnTime(c.due_at)}`;
    return `${name} ${when} · ${c.elapsed_minutes} of ${c.target_minutes} min used`;
  });
  return [`${badge.policy} · ${badge.calendar}`, ...lines].join("\n");
}

export default function SlaBadge({ badge }: { badge: SlaBadgeOut | null | undefined }) {
  if (!badge) return <span className="text-muted-foreground">—</span>;
  const text = tooltip(badge);
  return (
    <Badge variant={slaLevelTone(badge.level)} className="tabular-nums" title={text} aria-label={`${slaLabel(badge)}. ${text}`} tabIndex={0}>
      {slaLabel(badge)}
    </Badge>
  );
}

export function PriorityChip({ priority }: { priority: string | null | undefined }) {
  if (!priority) return <span className="text-muted-foreground">—</span>;
  return (
    <Badge variant={ticketPriorityTone(priority)} className="num">
      {priority}
    </Badge>
  );
}
