"use client";

// The status and stage chips of mass incidents (F7), and the ETA as Hà Nội reads it.

import { Badge, type Tone } from "@/components/ui/badge";

const STATUS: Record<string, Tone> = {
  proposed: "warn",
  confirmed: "danger",
  resolved: "ok",
  dismissed: "neutral",
  closed: "neutral",
};

const STAGE: Record<string, Tone> = {
  investigating: "warn",
  identified: "brand",
  monitoring: "brand",
  resolved: "ok",
};

export const STAGES = ["investigating", "identified", "monitoring", "resolved"] as const;

export function IncidentStatusChip({ status }: { status: string }) {
  return <Badge variant={STATUS[status] ?? "neutral"}>{status}</Badge>;
}

export function StageChip({ stage }: { stage: string }) {
  return <Badge variant={STAGE[stage] ?? "neutral"}>{stage}</Badge>;
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
