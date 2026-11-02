"use client";

// The SLA badge (F1 · SLA badge 8-604): business time left on the response clock until it is met,
// then on the resolution clock; the tooltip lists both.

import { slaLevelClasses, ticketPriorityClasses } from "@/lib/badges";
import type { SlaBadgeOut } from "@/lib/types/generated";

/** "35p", "3g 20p", "28g": business minutes in Vietnamese short units. */
export function businessDuration(minutes: number): string {
  const m = Math.abs(Math.round(minutes));
  if (m < 60) return `${m}p`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return h >= 24 || rest === 0 ? `${h}g` : `${h}g ${rest}p`;
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
      return `Quá hạn ${businessDuration(-badge.remaining_minutes)} · Breached`;
    case "at_risk":
      return `Còn ${businessDuration(badge.remaining_minutes)} · At risk`;
    case "paused":
      return "Tạm dừng · Paused";
    case "met":
      return "Đạt · Met";
    default:
      return `Còn ${businessDuration(badge.remaining_minutes)} · On track`;
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
  if (!badge) return <span className="text-[var(--text-muted)]">—</span>;
  const text = tooltip(badge);
  return (
    <span className={`badge ${slaLevelClasses(badge.level)}`} title={text} aria-label={`${slaLabel(badge)}. ${text}`} tabIndex={0}>
      {slaLabel(badge)}
    </span>
  );
}

export function PriorityChip({ priority }: { priority: string | null | undefined }) {
  if (!priority) return <span className="text-[var(--text-muted)]">—</span>;
  return <span className={`badge ${ticketPriorityClasses(priority)}`}>{priority}</span>;
}
