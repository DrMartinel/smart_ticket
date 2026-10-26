/**
 * Semantic tone for Branch / queue / risk_tier — kept in one place so a
 * tone always means the same thing across every page (spec's own principle
 * for TrustSignalsPanel: show WHY, consistently). The tones are defined in
 * globals.css.
 */

export function branchClasses(branch: string): string {
  switch (branch) {
    case "auto_reply":
      return "tone-ok";
    case "auto_route":
      return "tone-info";
    case "escalate":
      return "tone-warn";
    case "block":
      return "tone-danger";
    default:
      return "tone-neutral";
  }
}

export function riskTierClasses(tier: string): string {
  switch (tier) {
    case "low":
      return "tone-ok";
    case "medium":
      return "tone-warn";
    case "high":
      return "tone-danger";
    default:
      return "tone-neutral";
  }
}

export function priorityClasses(priority: number): string {
  if (priority <= 1) return "tone-danger";
  if (priority === 2) return "tone-warn";
  return "tone-neutral";
}

/** A ticket's or a placeholder's PII level: routine, sensitive, critical, mask_failed. */
export function piiLevelClasses(level: string): string {
  switch (level) {
    case "routine":
      return "tone-info";
    case "sensitive":
      return "tone-warn";
    case "critical":
      return "tone-danger";
    case "mask_failed":
      return "tone-alert";
    default:
      return "tone-neutral";
  }
}

/** A notification event: security first, then approvals, deadlines, assignment. */
export function notificationEventClasses(event: string): string {
  if (event.startsWith("security.") || event.startsWith("identity.")) return "tone-danger";
  if (event.startsWith("approval.") || event.startsWith("incident.")) return "tone-alert";
  if (event.startsWith("sla.") || event.startsWith("thresholds.")) return "tone-warn";
  if (event.startsWith("ticket.")) return "tone-info";
  return "tone-neutral";
}

/** A delivery's state: delivered, queued (or retrying), sending, failed. */
export function deliveryStateClasses(state: string, attempts = 0): string {
  switch (state) {
    case "delivered":
      return "tone-ok";
    case "failed":
      return "tone-danger";
    case "queued":
      return attempts > 0 ? "tone-warn" : "tone-neutral";
    default:
      return "tone-info";
  }
}

/** What a delivery state is called on screen: a queued message already tried is retrying. */
export function deliveryStateLabel(state: string, attempts = 0): string {
  if (state === "delivered") return "sent";
  if (state === "queued" && attempts > 0) return "retrying";
  return state;
}
