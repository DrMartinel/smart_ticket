"use client";

// The status and stage chips of mass incidents (F7), and the ETA as Hà Nội reads it.

const STATUS: Record<string, string> = {
  proposed: "bg-[var(--warn-soft)] text-[var(--warn)]",
  confirmed: "bg-[var(--danger-soft)] text-[var(--danger)]",
  resolved: "bg-[var(--ok-soft)] text-[var(--ok)]",
  dismissed: "bg-[var(--surface-2)] text-[var(--text-muted)]",
  closed: "bg-[var(--surface-2)] text-[var(--text-muted)]",
};

const STAGE: Record<string, string> = {
  investigating: "bg-[var(--warn-soft)] text-[var(--warn)]",
  identified: "bg-[var(--accent-soft)] text-[var(--accent)]",
  monitoring: "bg-[var(--accent-soft)] text-[var(--accent)]",
  resolved: "bg-[var(--ok-soft)] text-[var(--ok)]",
};

export const STAGES = ["investigating", "identified", "monitoring", "resolved"] as const;

export function IncidentStatusChip({ status }: { status: string }) {
  return <span className={`badge ${STATUS[status] ?? ""}`}>{status}</span>;
}

export function StageChip({ stage }: { stage: string }) {
  return <span className={`badge ${STAGE[stage] ?? ""}`}>{stage}</span>;
}

export function eta(at: string | null | undefined, unknown: boolean): string {
  if (unknown) return "chưa xác định";
  if (!at) return "—";
  return new Date(at).toLocaleString("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
  });
}

/** A `datetime-local` value (Hà Nội) as an ISO instant; empty for none. */
export function fromLocal(value: string): string | null {
  return value ? new Date(`${value}:00+07:00`).toISOString() : null;
}
