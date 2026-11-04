"use client";

// The Workspace's KB tabs (F6), who sees each one following the routes' gates, and KB display helpers.

import { usePathname } from "next/navigation";
import { canEditKb } from "@/lib/areas";
import type { CurrentUser } from "@/lib/auth";
import { Badge, type Tone } from "@/components/ui/badge";
import { TabNav } from "@/components/TabNav";

export { canEditKb };

interface Tab {
  href: string;
  label: string;
  show: boolean;
  exact?: boolean;
}

/** The Workspace's KB tabs: the pages and their content. */
export function KbTabs({ user }: { user: CurrentUser }) {
  const editor = canEditKb(user);
  return (
    <Tabs
      tabs={[
        { href: "/kb", label: "Trang · Pages", show: true, exact: true },
        { href: "/kb/drafts", label: "Drafts", show: editor },
        { href: "/kb/gaps", label: "Gaps", show: editor },
      ]}
    />
  );
}

function Tabs({ tabs }: { tabs: Tab[] }) {
  const pathname = usePathname();
  return (
    <TabNav
      tabs={tabs
        .filter((t) => t.show)
        .map((t) => ({ ...t, active: t.exact ? pathname === t.href : pathname.startsWith(t.href) }))}
    />
  );
}

const DRAFT_STATE: Record<string, Tone> = {
  draft: "neutral",
  in_review: "info",
  changes_requested: "warn",
  published: "ok",
  withdrawn: "neutral",
  conflict: "danger",
};

export const DRAFT_STATE_VI: Record<string, string> = {
  draft: "Draft",
  in_review: "In review",
  changes_requested: "Changes requested",
  published: "Published",
  withdrawn: "Withdrawn",
  conflict: "Conflict",
};

export function DraftStateChip({ state }: { state: string }) {
  return <Badge variant={DRAFT_STATE[state] ?? "neutral"}>{DRAFT_STATE_VI[state] ?? state}</Badge>;
}

export const KIND_VI: Record<string, string> = {
  create: "New page",
  edit: "Edit",
  retire: "Retire page",
};

export const AUTHORITY_REASON_VI: Record<string, string> = {
  new: "New page: no auto-reply yet",
  regrant: "Revoked: the text changed",
  tier: "Risk tier change proposed",
};

/** A unified-diff line as a coloured row; the `---`/`+++`/`@@` headers are dropped. */
export function DiffLines({ lines }: { lines: string[] }) {
  const shown = lines.filter((l) => !l.startsWith("---") && !l.startsWith("+++") && !l.startsWith("@@"));
  if (shown.length === 0) return <p className="text-xs text-muted-foreground">No changes.</p>;
  return (
    <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs leading-relaxed">
      {shown.map((l, i) => (
        <div
          key={i}
          className={
            l.startsWith("+")
              ? "bg-ok-soft text-ok"
              : l.startsWith("-")
                ? "bg-danger-soft text-danger line-through"
                : ""
          }
        >
          {l}
        </div>
      ))}
    </pre>
  );
}
