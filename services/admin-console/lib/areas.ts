// The console's two areas: the Workspace, where staff handle tickets, and Admin, where the system is set up and governed.

import type { CurrentUser } from "@/lib/auth";

export type Area = "workspace" | "admin";

export interface AdminLink {
  href: string;
  label: string;
  /** Highlighted when the path equals `href` instead of starting with it. */
  exact?: boolean;
  /** Highlighted when the path starts with this instead of `href`. */
  prefix?: string;
}

export interface AdminGroup {
  label: string;
  links: AdminLink[];
}

export function areaOf(pathname: string): Area {
  return pathname === "/admin" || pathname.startsWith("/admin/") ? "admin" : "workspace";
}

export function canEditKb(user: CurrentUser): boolean {
  return user.role === "manager" || (user.capabilities ?? []).includes("kb_editor");
}

/** The Admin sidebar's groups and the links `user` may open, in display order. */
export function adminGroups(user: CurrentUser): AdminGroup[] {
  const manager = user.role === "manager";
  const security = user.role === "security";
  const workflowAdmin = (user.capabilities ?? []).includes("workflow_admin");
  const settings = manager || workflowAdmin;
  const show = (on: boolean, link: AdminLink): AdminLink[] => (on ? [link] : []);

  const groups: AdminGroup[] = [
    {
      label: "Insights",
      links: [
        ...show(!security, { href: "/admin/dashboard", label: "Dashboard" }),
        ...show(true, { href: security ? "/admin/reports/security" : "/admin/reports", label: "Báo cáo · Reports", prefix: "/admin/reports" }),
        ...show(manager, { href: "/admin/security/summary", label: "Security alerts" }),
      ],
    },
    {
      label: "Governance",
      links: [
        ...show(manager, { href: "/admin/kb/authority", label: "Authority queue", exact: true }),
        ...show(manager, { href: "/admin/kb/pages", label: "All help pages" }),
        ...show(canEditKb(user) || security, { href: "/admin/kb/authority-log", label: "Authority log" }),
        ...show(settings || security, { href: "/admin/settings/rollout", label: "Rollout" }),
        ...show(settings, { href: "/admin/settings/thresholds", label: "Thresholds" }),
      ],
    },
    {
      label: "Settings",
      links: settings
        ? [
            ...show(manager, { href: "/admin/settings/workflows", label: "Workflows" }),
            { href: "/admin/settings/sla", label: "SLA policies", exact: true },
            { href: "/admin/settings/sla/calendars", label: "Calendars" },
            { href: "/admin/settings/sla/holidays", label: "Holidays" },
            { href: "/admin/settings/teams", label: "Teams" },
            { href: "/admin/settings/notifications", label: "Notifications" },
            { href: "/admin/settings/deliveries", label: "Delivery log" },
            { href: "/admin/settings/runbooks", label: "Runbooks" },
            ...show(workflowAdmin, { href: "/admin/settings/webhooks", label: "Webhooks" }),
          ]
        : [],
    },
  ];
  return groups.filter((g) => g.links.length > 0);
}

export function isActive(link: AdminLink, pathname: string): boolean {
  return link.exact ? pathname === link.href : pathname.startsWith(link.prefix ?? link.href);
}

/** The first Admin page `user` may open, or null when Admin has nothing for them. */
export function firstAdminPage(user: CurrentUser): string | null {
  return adminGroups(user)[0]?.links[0]?.href ?? null;
}
