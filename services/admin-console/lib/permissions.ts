// The permission URNs the console shows or hides things by (FR-F14-013); the server's check is what enforces them.

import type { CurrentUser } from "@/lib/auth";

const perm = (name: string) => `urn:smart-ticket:perm:${name}`;

export const P = {
  accessRead: perm("access:read"),
  accessGrant: perm("access:grant"),
  rolesManage: perm("access:roles:manage"),
  peopleRead: perm("access:people:read"),
  peopleManage: perm("access:people:manage"),
  reviewManage: perm("access:review:manage"),
  reviewRespond: perm("access:review:respond"),
  departmentsRead: perm("org:departments:read"),
  departmentsManage: perm("org:departments:manage"),
  orgImport: perm("org:import"),
  teamsManage: perm("teams:manage"),
} as const;

/** Whether the signed-in person holds `urn` anywhere. */
export function can(user: CurrentUser | null | undefined, urn: string): boolean {
  return !!user?.permissions?.includes(urn);
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
