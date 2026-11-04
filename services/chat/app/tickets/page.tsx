"use client";

// My tickets (F3 · My tickets 10-517): form and chat tickets, open first, then the last 30 days.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ChevronRight, Inbox, MessageSquare } from "lucide-react";
import AppHeader from "@/components/AppHeader";
import { day } from "@/components/Rating";
import { StatusChip } from "@/components/StatusChip";
import { requesterApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { RequesterTicketRow } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";

export default function MyTicketsPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState<RequesterTicketRow[] | null>(null);
  const [recent, setRecent] = useState<RequesterTicketRow[] | null>(null);
  const [more, setMore] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  const load = useCallback(() => {
    setError(false);
    requesterApi
      .list()
      .then((list) => {
        setOpen(list.open);
        setRecent(list.recent);
        setMore(list.more_before);
      })
      .catch(() => setError(true));
  }, []);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  const loadMore = async () => {
    if (!more) return;
    setLoadingMore(true);
    const page = await requesterApi.list(more).catch(() => null);
    setLoadingMore(false);
    if (!page) {
      toast.error("Couldn't load older tickets.");
      return;
    }
    setRecent((rows) => [...(rows ?? []), ...page.recent]);
    setMore(page.more_before);
  };

  if (!user) return null;
  const nothing = open?.length === 0 && recent?.length === 0;

  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader />
      <main id="main" className="flex-1">
        <Page width="form" className="flex flex-col gap-6 px-4 py-6 sm:px-6">
          <PageHeader
            eyebrow="My tickets"
            vi="Đơn của tôi"
            title="My tickets"
            description="Everything you've asked IT, from the chat and from forms. Open tickets come first."
          />
          {error && <ErrorState title="Couldn't load your tickets" onRetry={load} />}
          {!error && open === null && <LoadingState rows={4} label="Loading your tickets" />}
          {nothing ? (
            <EmptyState
              icon={Inbox}
              title="You haven't asked IT anything yet"
              action={
                <Button asChild>
                  <Link href="/">
                    <MessageSquare aria-hidden /> Ask a question
                  </Link>
                </Button>
              }
            >
              Questions you ask in the chat appear here, with their answer or the ticket they became.
            </EmptyState>
          ) : (
            open !== null && (
              <>
                <Section title="Open" rows={open} empty="Nothing open. Every ticket you raised is resolved." />
                <Section title="Last 30 days" rows={recent ?? []} empty="Nothing resolved in the last 30 days." />
                {more && (
                  <Button variant="outline" onClick={() => void loadMore()} disabled={loadingMore} className="self-center">
                    {loadingMore ? "Loading…" : "Show older tickets"}
                  </Button>
                )}
              </>
            )
          )}
        </Page>
      </main>
    </div>
  );
}

function Section({ title, rows, empty }: { title: string; rows: RequesterTicketRow[]; empty: string }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="eyebrow flex items-center gap-2">
        {title}
        <span className="num normal-case">{rows.length}</span>
      </h2>
      {rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-border-strong px-4 py-3 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="divide-y divide-border overflow-hidden rounded-md border border-border bg-card">
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
  const facts = [row.team ?? (row.source === "chat" ? "Chat" : "Form ticket")];
  if (row.sla_paused) facts.push("Waiting for you");
  else if (row.resolution_due_at) facts.push(`Due ${day(row.resolution_due_at)}`);
  if (row.can_reopen_until && Date.parse(row.can_reopen_until) > Date.now()) facts.push(`Reopen until ${day(row.can_reopen_until)}`);
  if (row.rating) facts.push(`Rated ${row.rating}/5`);
  const done = row.resolved_at !== null;
  return (
    <Link href={`/tickets/${row.public_id}`} className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/60">
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="num text-2xs text-muted-foreground">{row.public_id}</span>
          <StatusChip label={row.status_label} waiting={row.sla_paused} done={done} />
          {row.unread_comments > 0 && (
            <span className="rounded-full bg-danger-soft px-2 py-0.5 text-2xs font-medium text-danger">
              {row.unread_comments} new {row.unread_comments === 1 ? "reply" : "replies"}
            </span>
          )}
          {done && !row.rating && row.can_reopen_until && Date.parse(row.can_reopen_until) > Date.now() && (
            <span className="text-2xs font-medium text-primary">Rate the help</span>
          )}
        </span>
        <span className="mt-1 line-clamp-2 text-[15px] leading-6">{row.subject_masked}</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">{facts.join(" · ")}</span>
      </span>
      <ChevronRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
    </Link>
  );
}
