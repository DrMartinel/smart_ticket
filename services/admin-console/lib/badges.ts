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
