"use client";

// A row of tabs, one link per page, and the tabs of the Admin section the current page is in.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { isActive, sectionTabs } from "@/lib/areas";

export interface TabLink {
  href: string;
  label: string;
  active: boolean;
}

export function TabNav({ tabs, className = "mb-5" }: { tabs: TabLink[]; className?: string }) {
  return (
    <nav className={`flex flex-wrap gap-5 border-b border-border text-sm ${className}`}>
      {tabs.map((t) => (
        <Link
          key={t.href}
          href={t.href}
          aria-current={t.active ? "page" : undefined}
          className={`-mb-px border-b-2 pb-2 ${
            t.active
              ? "border-primary font-medium text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}

/** The current Admin section's tabs, or nothing when the page isn't in a tabbed section. */
export function SectionTabs({ className }: { className?: string }) {
  const pathname = usePathname() ?? "";
  const { user } = useAuth();
  if (!user) return null;
  const tabs = sectionTabs(user, pathname);
  if (tabs.length === 0) return null;
  return (
    <TabNav
      className={className}
      tabs={tabs.map((t) => ({ href: t.href, label: t.label, active: isActive(t, pathname) }))}
    />
  );
}
