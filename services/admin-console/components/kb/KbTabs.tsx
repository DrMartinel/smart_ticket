"use client";

// The KB section's tabs (F6): who sees each one follows the routes' gates.

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { CurrentUser } from "@/lib/auth";

export function canEditKb(user: CurrentUser): boolean {
  return user.role === "manager" || (user.capabilities ?? []).includes("kb_editor");
}

export function KbTabs({ user }: { user: CurrentUser }) {
  const pathname = usePathname();
  const editor = canEditKb(user);
  const tabs = [
    { href: "/kb", label: "Trang · Pages", show: true, exact: true },
    { href: "/kb/drafts", label: "Bản nháp · Drafts", show: editor },
    { href: "/kb/authority", label: "Hàng chờ quyền · Authority queue", show: user.role === "manager" },
    {
      href: "/kb/authority-log",
      label: "Nhật ký quyền · Authority log",
      show: editor || user.role === "security",
    },
    { href: "/kb/gaps", label: "Thiếu KB · Gaps", show: editor },
  ];
  return (
    <nav className="mb-5 flex flex-wrap gap-5 border-b border-[var(--border)] text-sm">
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
                  ? "border-[var(--accent)] font-medium text-[var(--accent)]"
                  : "border-transparent text-[var(--text-muted)] hover:text-[var(--text)]"
              }`}
            >
              {t.label}
            </Link>
          );
        })}
    </nav>
  );
}

const DRAFT_STATE: Record<string, string> = {
  draft: "tone-neutral",
  in_review: "tone-info",
  changes_requested: "tone-warn",
  published: "tone-ok",
  withdrawn: "tone-neutral",
  conflict: "tone-danger",
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
  return <span className={`badge ${DRAFT_STATE[state] ?? ""}`}>{DRAFT_STATE_VI[state] ?? state}</span>;
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
  if (shown.length === 0) return <p className="text-xs text-[var(--text-muted)]">Không thay đổi.</p>;
  return (
    <pre className="overflow-x-auto whitespace-pre-wrap rounded-[5px] bg-[var(--surface-2)] p-3 text-xs leading-relaxed">
      {shown.map((l, i) => (
        <div
          key={i}
          className={
            l.startsWith("+")
              ? "bg-[var(--ok-soft)] text-[var(--ok)]"
              : l.startsWith("-")
                ? "bg-[var(--danger-soft)] text-[var(--danger)] line-through"
                : ""
          }
        >
          {l}
        </div>
      ))}
    </pre>
  );
}
