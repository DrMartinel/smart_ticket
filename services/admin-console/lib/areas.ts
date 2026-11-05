// The console's two areas: the Workspace, where staff handle tickets, and Admin, where the system is set up and governed.

import type { CurrentUser } from "@/lib/auth";
import { P, can } from "@/lib/permissions";

export type Area = "workspace" | "admin";

export interface AdminLink {
  href: string;
  label: string;
  /** Highlighted when the path equals `href` instead of starting with it. */
  exact?: boolean;
  /** Highlighted when the path starts with this instead of `href`. */
  prefix?: string;
  /** The section's pages, shown as tabs on each of them; `href` is the first one's. */
  tabs?: AdminLink[];
}

export interface AdminGroup {
  label: string;
  links: AdminLink[];
}

export function areaOf(pathname: string): Area {
  return pathname === "/admin" || pathname.startsWith("/admin/") ? "admin" : "workspace";
}

export function canEditKb(user: CurrentUser): boolean {
  return can(user, P.kbDraftsManage);
}

/** The Admin sidebar's groups and the links `user` may open, in display order. */
export function adminGroups(user: CurrentUser): AdminGroup[] {
  const show = (on: boolean, link: AdminLink): AdminLink[] => (on ? [link] : []);
  const securityReportsOnly = can(user, P.reportsSecurity) && !can(user, P.reportsDashboard);
  const anyReport = [P.reportsOperations, P.reportsTeams, P.reportsKb, P.reportsRollout, P.reportsSecurity, P.reportsIncidents, P.reportsNotifications].some(
    (urn) => can(user, urn),
  );

  const groups: AdminGroup[] = [
    {
      label: "Insights",
      links: [
        ...show(can(user, P.reportsDashboard), { href: "/admin/dashboard", label: "Dashboard" }),
        ...show(anyReport, { href: securityReportsOnly ? "/admin/reports/security" : "/admin/reports", label: "Reports", prefix: "/admin/reports" }),
        ...show(can(user, P.securitySummary) && !can(user, P.securityQueue), { href: "/admin/security/summary", label: "Security alerts" }),
      ],
    },
    {
      label: "Governance",
      links: [
        ...section("Help pages", [
          ...show(can(user, P.kbAuthorityQueue), { href: "/admin/kb/authority", label: "Authority queue", exact: true }),
          ...show(can(user, P.kbAuthorityQueue), { href: "/admin/kb/pages", label: "All help pages" }),
          ...show(can(user, P.kbAuthorityLog), { href: "/admin/kb/authority-log", label: "Authority log" }),
        ]),
        ...section("Rollout", [
          ...show(can(user, P.rolloutOff), { href: "/admin/settings/rollout", label: "Rollout" }),
          ...show(can(user, P.rolloutOff) && can(user, P.thresholdsRead), { href: "/admin/settings/thresholds", label: "Thresholds" }),
        ]),
      ],
    },
    {
      label: "Settings",
      links: [
        ...show(can(user, P.workflowsManage), { href: "/admin/settings/workflows", label: "Workflows" }),
        ...section(
          "SLA",
          can(user, P.slaManage) || can(user, P.slaActivate)
            ? [
                { href: "/admin/settings/sla", label: "Policies", exact: true },
                { href: "/admin/settings/sla/calendars", label: "Calendars" },
                { href: "/admin/settings/sla/holidays", label: "Holidays" },
              ]
            : [],
        ),
        ...section("People & access", [
          ...show(can(user, P.peopleRead), { href: "/admin/settings/people", label: "People" }),
          ...show(can(user, P.departmentsRead), { href: "/admin/settings/departments", label: "Departments" }),
          ...show(can(user, P.teamsManage), { href: "/admin/settings/teams", label: "Teams" }),
          ...show(can(user, P.accessRead), { href: "/admin/settings/roles", label: "Roles" }),
          ...show(can(user, P.reviewManage), { href: "/admin/settings/access-reviews", label: "Access reviews" }),
        ]),
        ...section("Notifications", [
          ...show(can(user, P.notificationsMatrixRead), { href: "/admin/settings/notifications", label: "Matrix" }),
          ...show(can(user, P.notificationsDeliveries), { href: "/admin/settings/deliveries", label: "Delivery log" }),
          ...show(can(user, P.notificationsWebhooksManage), { href: "/admin/settings/webhooks", label: "Webhooks" }),
        ]),
        ...show(can(user, P.runbooksManage) || can(user, P.runbooksActivate), { href: "/admin/settings/runbooks", label: "Runbooks" }),
      ],
    },
  ];
  return groups.filter((g) => g.links.length > 0);
}

/** One sidebar link for a section's pages: a tabbed link for two or more, else the one page's own. */
function section(label: string, tabs: AdminLink[]): AdminLink[] {
  return tabs.length < 2 ? tabs : [{ href: tabs[0].href, label, tabs }];
}

export function isActive(link: AdminLink, pathname: string): boolean {
  if (link.tabs) return link.tabs.some((t) => isActive(t, pathname));
  return link.exact ? pathname === link.href : pathname.startsWith(link.prefix ?? link.href);
}

/** The first Admin page `user` may open, or null when Admin has nothing for them. */
export function firstAdminPage(user: CurrentUser): string | null {
  return adminGroups(user)[0]?.links[0]?.href ?? null;
}

/** The tabs of the Admin section `pathname` is in, or none when it isn't in a tabbed one. */
export function sectionTabs(user: CurrentUser, pathname: string): AdminLink[] {
  const links = adminGroups(user).flatMap((g) => g.links);
  return links.find((l) => l.tabs && isActive(l, pathname))?.tabs ?? [];
}
