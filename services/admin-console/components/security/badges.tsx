"use client";

// The severity and state chips of the security inbox (F8).

const SEVERITY: Record<string, string> = {
  critical: "bg-[var(--danger-soft)] text-[var(--danger)]",
  high: "bg-[var(--warn-soft)] text-[var(--warn)]",
  medium: "bg-[var(--surface-2)] text-[var(--text-muted)]",
};

const STATE: Record<string, string> = {
  new: "bg-[var(--accent-soft)] text-[var(--accent)]",
  acknowledged: "bg-[var(--ok-soft)] text-[var(--ok)]",
  investigating: "bg-[var(--warn-soft)] text-[var(--warn)]",
  closed: "bg-[var(--surface-2)] text-[var(--text-muted)]",
};

export function SeverityChip({ severity }: { severity: string }) {
  return <span className={`badge ${SEVERITY[severity] ?? ""}`}>{severity}</span>;
}

export function StateChip({ state, resolution }: { state: string; resolution?: string | null }) {
  return (
    <span className={`badge ${STATE[state] ?? ""}`}>
      {state}
      {resolution ? ` · ${resolution}` : ""}
    </span>
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
