// The permission URNs the console shows or hides things by (FR-F14-013); the server's check is what enforces them.

import type { CurrentUser } from "@/lib/auth";

const perm = (name: string) => `urn:smart-ticket:perm:${name}`;

export const P = {
  accessRead: perm("access:read"),
  accessGrant: perm("access:grant"),
  grantDelegable: perm("access:grant:delegable"),
  rolesManage: perm("access:roles:manage"),
  peopleRead: perm("access:people:read"),
  peopleManage: perm("access:people:manage"),
  reviewManage: perm("access:review:manage"),
  reviewRespond: perm("access:review:respond"),
  departmentsRead: perm("org:departments:read"),
  departmentsManage: perm("org:departments:manage"),
  orgImport: perm("org:import"),
  incidentsManage: perm("incidents:manage"),
  incidentsRead: perm("incidents:read"),
  incidentsUnlink: perm("incidents:unlink"),
  kbAuthorityGrant: perm("kb:authority:grant"),
  kbAuthorityQueue: perm("kb:authority:queue"),
  kbAuthorityLog: perm("kb:authority-log:read"),
  kbDraftsManage: perm("kb:drafts:manage"),
  kbDraftsWithdrawAny: perm("kb:drafts:withdraw-any"),
  kbGraphEdit: perm("kb:graph:edit"),
  kbPagesCreate: perm("kb:pages:create"),
  notificationsMatrixManage: perm("notifications:matrix:manage"),
  notificationsMatrixRead: perm("notifications:matrix:read"),
  notificationsTemplatesManage: perm("notifications:templates:manage"),
  notificationsWebhooksManage: perm("notifications:webhooks:manage"),
  notificationsDeliveries: perm("notifications:deliveries:manage"),
  piiReveal: perm("pii:reveal"),
  piiRevealAny: perm("pii:reveal:any"),
  piiAccessLog: perm("pii:access-log:read"),
  reportsDashboard: perm("reports:dashboard:read"),
  reportsOperations: perm("reports:operations:read"),
  reportsTeams: perm("reports:teams:read"),
  reportsReviewersAll: perm("reports:reviewers:all"),
  reportsKb: perm("reports:kb:read"),
  reportsRollout: perm("reports:rollout:read"),
  reportsSecurity: perm("reports:security:read"),
  reportsIncidents: perm("reports:incidents:read"),
  reportsNotifications: perm("reports:notifications:read"),
  reviewQueue: perm("review:queue:work"),
  rolloutRead: perm("rollout:read"),
  rolloutOn: perm("rollout:flag:on"),
  rolloutOff: perm("rollout:flag:off"),
  rolloutGates: perm("rollout:gates:manage"),
  thresholdsRead: perm("rollout:thresholds:read"),
  runbooksRead: perm("runbooks:catalog:read"),
  runbooksManage: perm("runbooks:catalog:manage"),
  runbooksActivate: perm("runbooks:catalog:activate"),
  runbooksExecute: perm("runbooks:execute"),
  securityQueue: perm("security:queue:work"),
  securitySummary: perm("security:summary:read"),
  slaRead: perm("sla:read"),
  slaManage: perm("sla:manage"),
  slaActivate: perm("sla:policies:activate"),
  teamsRead: perm("teams:read"),
  teamsManage: perm("teams:manage"),
  availabilityOwn: perm("teams:availability:own"),
  teamsSupervise: perm("teams:supervise"),
  ticketsRead: perm("tickets:read"),
  ticketsComment: perm("tickets:comment"),
  ticketsTake: perm("tickets:take"),
  ticketsPriority: perm("tickets:priority"),
  ticketsAllCategories: perm("tickets:all-categories"),
  workflowsRead: perm("workflows:read"),
  workflowsManage: perm("workflows:manage"),
} as const;

/** Whether the signed-in person holds `urn` anywhere. */
export function can(user: CurrentUser | null | undefined, urn: string): boolean {
  return !!user?.permissions?.includes(urn);
}

/** Whether the signed-in person holds `urn` everywhere, not only for some teams or departments. */
export function canEverywhere(user: CurrentUser | null | undefined, urn: string): boolean {
  return !!user?.permissions_everywhere?.includes(urn);
}

/** Whether the person may supervise team `slug`: as its lead, or by a supervise grant (the server checks which teams). */
export function supervises(user: CurrentUser | null | undefined, slug: string): boolean {
  return can(user, P.teamsSupervise) || !!user?.teams?.some((t) => t.team === slug && t.role === "lead");
}

/** A role or permission URN's last segments, e.g. `custom:read-only-auditor`. */
export function shortUrn(urn: string): string {
  return urn.replace(/^urn:smart-ticket:(perm|role):/, "");
}

export const SCOPE_LABEL: Record<string, string> = {
  global: "Everywhere",
  team: "One team",
  department: "A department and below",
};

export const END_REASON_LABEL: Record<string, string> = {
  ended: "ended by hand",
  expired: "expired",
  rights_changed: "rights changed",
  became_employee: "became an employee",
  left_team: "left the team",
  no_longer_lead: "no longer lead",
  no_longer_head: "no longer head",
  role_retired: "role retired",
  department_archived: "department archived",
  mover_unconfirmed: "not confirmed after a move",
  review_revoked: "revoked in review",
  review_no_answer: "unanswered in review",
  deactivated: "person left",
};

/** The roles nobody grants by hand: base roles come from the People list, team lead and department head from the structure. */
export const UNGRANTABLE_ROLES = new Set(
  ["employee", "technician", "manager", "security", "team-lead", "department-head"].map((n) => `urn:smart-ticket:role:system:${n}`),
);
