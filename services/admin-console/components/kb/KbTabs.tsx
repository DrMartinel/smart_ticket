"use client";

// The KB tabs (F6) in each area: who sees each one follows the routes' gates.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { canEditKb } from "@/lib/areas";
import type { CurrentUser } from "@/lib/auth";
import { Badge, type Tone } from "@/components/ui/badge";

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
        { href: "/kb/drafts", label: "Bản nháp · Drafts", show: editor },
        { href: "/kb/gaps", label: "Thiếu KB · Gaps", show: editor },
      ]}
    />
  );
}

/** Admin's KB tabs: who may answer automatically from which page. */
export function AuthorityTabs({ user }: { user: CurrentUser }) {
  const manager = user.role === "manager";
  return (
    <Tabs
      tabs={[
        { href: "/admin/kb/authority", label: "Hàng chờ quyền · Authority queue", show: manager, exact: true },
        { href: "/admin/kb/pages", label: "Tất cả trang · All pages", show: manager },
        {
          href: "/admin/kb/authority-log",
          label: "Nhật ký quyền · Authority log",
          show: canEditKb(user) || user.role === "security",
        },
      ]}
    />
  );
}

function Tabs({ tabs }: { tabs: Tab[] }) {
  const pathname = usePathname();
  return (
    <nav className="mb-5 flex flex-wrap gap-5 border-b border-border text-sm">
      {tabs
        .filter((t) => t.show)
        .map((t) => {
          const active = t.exact ? pathname === t.href : pathname.startsWith(t.href);
          return (
            <Link
              key={t.href}
              href={t.href}
              className={`-mb-px border-b-2 pb-2 ${
                active
                  ? "border-primary font-medium text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t.label}
            </Link>
          );
        })}
    </nav>
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

const DRAFT_STATE_VI: Record<string, string> = {
  draft: "Nháp",
  in_review: "Chờ duyệt",
  changes_requested: "Cần sửa",
  published: "Đã xuất bản",
  withdrawn: "Đã rút",
  conflict: "Xung đột",
};

export function DraftStateChip({ state }: { state: string }) {
  return <Badge variant={DRAFT_STATE[state] ?? "neutral"}>{DRAFT_STATE_VI[state] ?? state}</Badge>;
}

export const KIND_VI: Record<string, string> = {
  create: "Trang mới",
  edit: "Sửa",
  retire: "Gỡ trang",
};

export const AUTHORITY_REASON_VI: Record<string, string> = {
  new: "Trang mới: chưa có quyền trả lời tự động",
  regrant: "Bị thu hồi: nội dung đã thay đổi",
  tier: "Đề xuất đổi mức rủi ro",
};

/** A unified-diff line as a coloured row; the `---`/`+++`/`@@` headers are dropped. */
export function DiffLines({ lines }: { lines: string[] }) {
  const shown = lines.filter((l) => !l.startsWith("---") && !l.startsWith("+++") && !l.startsWith("@@"));
  if (shown.length === 0) return <p className="text-xs text-muted-foreground">Không thay đổi.</p>;
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
