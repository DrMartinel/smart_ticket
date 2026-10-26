"use client";

// My tickets (F3 · My tickets 10-517): form and chat tickets, open first, then the last 30 days.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import AppHeader from "@/components/AppHeader";
import { day } from "@/components/Rating";
import { requesterApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { RequesterTicketRow } from "@/lib/types/generated";

export default function MyTicketsPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState<RequesterTicketRow[] | null>(null);
  const [recent, setRecent] = useState<RequesterTicketRow[]>([]);
  const [more, setMore] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    requesterApi
      .list()
      .then((list) => {
        setOpen(list.open);
        setRecent(list.recent);
        setMore(list.more_before);
      })
      .catch(() => setError("Không tải được · Couldn't load your tickets."));
  }, [user]);

  const loadMore = async () => {
    if (!more) return;
    const page = await requesterApi.list(more).catch(() => null);
    if (!page) return;
    setRecent((rows) => [...rows, ...page.recent]);
    setMore(page.more_before);
  };

  if (!user) return null;

  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader />
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6 md:px-6">
        <h1 className="text-xl font-semibold">Đơn của tôi · My tickets</h1>
        {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
        <Section title="Đang mở · Open" rows={open} empty="Không có yêu cầu đang mở · Nothing open." />
        <Section title="30 ngày qua · Last 30 days" rows={recent} empty="Chưa có · None yet." />
        {more && (
          <button onClick={() => void loadMore()} className="btn btn-secondary self-center">
            Xem thêm · Show older
          </button>
        )}
      </main>
    </div>
  );
}

function Section({ title, rows, empty }: { title: string; rows: RequesterTicketRow[] | null; empty: string }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">{title}</h2>
      {rows === null ? (
        <p className="text-sm text-[var(--text-muted)]">…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-[var(--text-muted)]">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((row) => (
            <li key={row.public_id}>
              <TicketRow row={row} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function TicketRow({ row }: { row: RequesterTicketRow }) {
  const facts = [row.public_id, row.team ?? (row.source === "chat" ? "chat" : "form ticket")];
  if (row.sla_paused) facts.push("SLA paused while we wait for you");
  else if (row.resolution_due_at) facts.push(`due ${day(row.resolution_due_at)}`);
  if (row.can_reopen_until && Date.parse(row.can_reopen_until) > Date.now())
    facts.push(`reopen until ${day(row.can_reopen_until)}`);
  if (row.rating) facts.push(`rated ${row.rating}`);
  const waiting = row.sla_paused;
  const done = row.resolved_at !== null;
  return (
    <Link
      href={`/tickets/${row.public_id}`}
      className="panel flex items-center justify-between gap-3 px-4 py-3 transition-colors hover:border-[var(--text-muted)]"
    >
      <span className="min-w-0">
        <span className="line-clamp-2 text-[15px]">{row.subject_masked}</span>
        <span className="mt-0.5 block text-xs text-[var(--text-muted)]">{facts.join(" · ")}</span>
      </span>
      <span className="flex shrink-0 flex-wrap items-center justify-end gap-2">
        {row.unread_comments > 0 && (
          <span className="rounded-full bg-[var(--danger-soft)] px-2 py-0.5 text-xs text-[var(--danger)]">
            {row.unread_comments} new {row.unread_comments === 1 ? "reply" : "replies"}
          </span>
        )}
        {done && !row.rating && row.can_reopen_until && Date.parse(row.can_reopen_until) > Date.now() && (
          <span className="text-xs text-[var(--accent)]">Rate ☆</span>
        )}
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
            waiting
              ? "bg-[var(--warn-soft)] text-[var(--warn)]"
              : done
                ? "bg-[var(--ok-soft)] text-[var(--ok)]"
                : "bg-[var(--accent-soft)] text-[var(--accent)]"
          }`}
        >
          {row.status_label}
        </span>
      </span>
    </Link>
  );
}
