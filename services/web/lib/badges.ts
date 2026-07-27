/**
 * Semantic color mapping for Branch / queue / risk_tier — kept in one
 * place so a color always means the same thing across every page
 * (spec's own principle for TrustSignalsPanel: show WHY, consistently).
 */

export function branchClasses(branch: string): string {
  switch (branch) {
    case "auto_reply":
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300";
    case "auto_route":
      return "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300";
    case "hitl":
      return "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300";
    case "escalate":
      return "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300";
    case "block":
      return "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300";
    default:
      return "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300";
  }
}

export function riskTierClasses(tier: string): string {
  switch (tier) {
    case "low":
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300";
    case "medium":
      return "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300";
    case "high":
      return "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300";
    default:
      return "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300";
  }
}

export function priorityClasses(priority: number): string {
  if (priority <= 1) return "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300";
  if (priority === 2) return "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300";
  return "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300";
}
