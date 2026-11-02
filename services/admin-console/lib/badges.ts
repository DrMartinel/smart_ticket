/** Semantic badge tone for Branch, queue and risk tier, one meaning on every page. */

import type { Tone } from "@/components/ui/badge";

export function branchTone(branch: string): Tone {
  switch (branch) {
    case "auto_reply":
      return "ok";
    case "auto_route":
      return "info";
    case "escalate":
      return "warn";
    case "block":
      return "danger";
    default:
      return "neutral";
  }
}

export function riskTierTone(tier: string): Tone {
  switch (tier) {
    case "low":
      return "ok";
    case "medium":
      return "warn";
    case "high":
      return "danger";
    default:
      return "neutral";
  }
}

export function priorityTone(priority: number): Tone {
  if (priority <= 1) return "danger";
  if (priority === 2) return "warn";
  return "neutral";
}

/** A ticket's or a placeholder's PII level: routine, sensitive, critical, mask_failed. */
export function piiLevelTone(level: string): Tone {
  switch (level) {
    case "routine":
      return "info";
    case "sensitive":
      return "warn";
    case "critical":
      return "danger";
    case "mask_failed":
      return "alert";
    default:
      return "neutral";
  }
}

/** A notification event: security first, then approvals, deadlines, assignment. */
export function notificationEventTone(event: string): Tone {
  if (event.startsWith("security.") || event.startsWith("identity.")) return "danger";
  if (event.startsWith("approval.") || event.startsWith("incident.")) return "alert";
  if (event.startsWith("sla.") || event.startsWith("thresholds.")) return "warn";
  if (event.startsWith("ticket.")) return "info";
  return "neutral";
}

/** A delivery's state: delivered, queued (or retrying), sending, failed. */
export function deliveryStateTone(state: string, attempts = 0): Tone {
  switch (state) {
    case "delivered":
      return "ok";
    case "failed":
      return "danger";
    case "queued":
      return attempts > 0 ? "warn" : "neutral";
    default:
      return "info";
  }
}

/** What a delivery state is called on screen: a queued message already tried is retrying. */
export function deliveryStateLabel(state: string, attempts = 0): string {
  if (state === "delivered") return "sent";
  if (state === "queued" && attempts > 0) return "retrying";
  return state;
}

/** A ticket priority, P1 (critical) to P4 (low). */
export function ticketPriorityTone(priority: string | null | undefined): Tone {
  switch (priority) {
    case "P1":
      return "danger";
    case "P2":
      return "warn";
    default:
      return "neutral";
  }
}

/** An SLA badge level: on_track, at_risk, breached, paused, met. */
export function slaLevelTone(level: string): Tone {
  switch (level) {
    case "on_track":
      return "info";
    case "at_risk":
      return "warn";
    case "breached":
      return "danger";
    case "met":
      return "ok";
    default:
      return "neutral";
  }
}
