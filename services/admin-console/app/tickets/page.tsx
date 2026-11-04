"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useRequireAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { QUEUE_LABEL } from "@/lib/explain";
import { dateTime, humanize, relativeTime } from "@/lib/format";
import { VIEWS } from "@/lib/views";
import StatusChip from "@/components/StatusChip";
import SlaBadge, { PriorityChip } from "@/components/SlaBadge";
import { priorityTone } from "@/lib/badges";
import type { StaffTicketPage } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import Link from "next/link";
import { CheckCheck, Inbox, Layers, ListChecks, Search, SearchX, UserRound, type LucideIcon } from "lucide-react";
import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";

type TicketPage = StaffTicketPage;

const PAGE_SIZE = 50;

const EMPTY: Record<string, { icon: LucideIcon; title: string; body: string }> = {
  review: { icon: ListChecks, title: "Nothing is waiting for review", body: "When triage sends a ticket to a person, it appears here for someone to claim." },
  mine: { icon: UserRound, title: "No open tickets are assigned to you", body: "Take one from your team's queue, or claim a review from Needs review." },
  open: { icon: Inbox, title: "No open tickets", body: "New tickets from the chat and the form land here once triage has run." },
  resolved: { icon: CheckCheck, title: "No resolved tickets yet", body: "Tickets show up here once they are answered or closed." },
  all: { icon: Layers, title: "No tickets yet", body: "Tickets appear as soon as someone asks a question in IT Help or submits the form." },
};

const DESCRIPTION: Record<string, string> = {
  review: "Tickets triage sent to a person. Claim one to decide what happens.",
  mine: "Open tickets assigned to you.",
  open: "Every ticket that isn't resolved yet.",
  resolved: "Tickets that were answered or closed.",
  all: "Every ticket, newest first.",
};

export default function TicketsPage() {
  const user = useRequireAuth();
  const router = useRouter();
  const search = useSearchParams();
  const view = search.get("view") ?? "review";
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<TicketPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => setPage(1), [view, submitted]);

  useEffect(() => {
    if (!user) return;
    let current = true;
    setData(null);
    setError(null);
    const params = new URLSearchParams({ view, page: String(page), limit: String(PAGE_SIZE) });
    if (submitted) params.set("q", submitted);
    api
      .get<TicketPage>(`/api/tickets?${params}`)
      .then((result) => current && setData(result))
      .catch(() => current && setError("The ticket service didn't respond. Check your connection and try again."));
    return () => {
      current = false;
    };
  }, [user, view, page, submitted, attempt]);

  if (!user) return null;

  const title = VIEWS.find((v) => v.key === view)?.label ?? "Tickets";
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  const retry = () => setAttempt((n) => n + 1);
  const empty = EMPTY[view] ?? EMPTY.all;

  return (
    <Page>
      <PageHeader
        eyebrow="Workspace / Tickets"
        title={title}
        description={
          data ? (
            <>
              <span className="num">{data.total}</span> ticket{data.total === 1 ? "" : "s"}
              {submitted && <> matching &ldquo;{submitted}&rdquo;</>}
            </>
          ) : (
            DESCRIPTION[view] ?? DESCRIPTION.all
          )
        }
        actions={
          <form
            role="search"
            onSubmit={(e) => {
              e.preventDefault();
              setSubmitted(query.trim());
            }}
            className="flex w-full gap-2 sm:w-auto"
          >
            <div className="relative min-w-0 flex-1 sm:w-72 sm:flex-none">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ticket ID or subject"
                aria-label="Search tickets by ID or subject"
                className="pl-9"
              />
            </div>
            <Button variant="outline" type="submit">
              Search
            </Button>
          </form>
        }
      />

      {error && <ErrorState title="Couldn't load tickets" onRetry={retry}>{error}</ErrorState>}

      {!error && !data && (
        <Card className="px-4 py-3">
          <LoadingState rows={6} label="Loading tickets" />
        </Card>
      )}

      {data && data.items.length === 0 && (
        <Card>
          {submitted ? (
            <EmptyState
              icon={SearchX}
              title={`No tickets match "${submitted}"`}
              action={
                <Button
                  variant="outline"
                  onClick={() => {
                    setQuery("");
                    setSubmitted("");
                  }}
                >
                  Clear search
                </Button>
              }
            >
              Search looks at ticket IDs and subjects in this view. Try the ID (e.g. TCK-2026-00412) or{" "}
              <Link href="/tickets?view=all" className="text-primary underline-offset-2 hover:underline">
                all tickets
              </Link>
              .
            </EmptyState>
          ) : (
            <EmptyState icon={empty.icon} title={empty.title}>
              {empty.body}
            </EmptyState>
          )}
        </Card>
      )}

      {data && data.items.length > 0 && (
        <Card className="overflow-hidden">
          <ul className="divide-y divide-border md:hidden">
            {data.items.map((t) => (
              <li key={t.public_id}>
                <Link href={`/tickets/${t.public_id}`} className="block px-4 py-3 transition-colors duration-150 hover:bg-muted/50">
                  <span className="flex items-start justify-between gap-3">
                    <span className="min-w-0 font-medium leading-snug">{t.subject_masked}</span>
                    <span className="num shrink-0 pt-0.5 text-xs text-muted-foreground" title={dateTime(t.created_at)}>
                      {relativeTime(t.created_at)}
                    </span>
                  </span>
                  <span className="mt-1 block truncate text-xs text-muted-foreground">
                    <span className="num">{t.public_id}</span> · {t.reporter}
                    {t.category && ` · ${t.category}`}
                  </span>
                  <span className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    <StatusChip name={t.status.name} color={t.status.color} />
                    {t.review && (
                      <span className="inline-flex items-center gap-1.5 text-[13px]">
                        <Badge variant={priorityTone(t.review.priority)} className="num">P{t.review.priority}</Badge>
                        {QUEUE_LABEL[t.review.queue] ?? humanize(t.review.queue)}
                      </span>
                    )}
                    <SlaBadge badge={t.sla} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <Table className="hidden min-w-[640px] table-fixed md:table">
            <TableHeader>
              <TableRow>
                <TableHead>Ticket</TableHead>
                <TableHead className="w-44">Status</TableHead>
                <TableHead className="w-52">Needs</TableHead>
                <TableHead className="hidden w-40 xl:table-cell">Owner</TableHead>
                <TableHead className="hidden w-56 xl:table-cell">SLA</TableHead>
                <TableHead className="hidden w-28 text-right lg:table-cell">Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((t) => (
                <TableRow
                  key={t.public_id}
                  onClick={() => router.push(`/tickets/${t.public_id}`)}
                  className="cursor-pointer align-top"
                >
                  <TableCell className="py-3">
                    <a
                      href={`/tickets/${t.public_id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="block truncate font-medium hover:text-primary"
                      title={t.subject_masked}
                    >
                      {t.subject_masked}
                    </a>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      <span className="num">{t.public_id}</span> · {t.reporter} · {humanize(t.source)}
                      {t.category && ` · ${t.category}`}
                    </p>
                  </TableCell>
                  <TableCell className="py-3">
                    <StatusChip name={t.status.name} color={t.status.color} />
                  </TableCell>
                  <TableCell className="py-3">
                    {t.review ? (
                      <span className="inline-flex items-center gap-2">
                        <Badge variant={priorityTone(t.review.priority)} className="num">P{t.review.priority}</Badge>
                        <span className="whitespace-nowrap">{QUEUE_LABEL[t.review.queue] ?? humanize(t.review.queue)}</span>
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="hidden py-3 whitespace-nowrap xl:table-cell">
                    {t.assignee ?? <span className="text-muted-foreground">Unassigned</span>}
                    {t.assigned_team && <p className="text-xs text-muted-foreground">{t.assigned_team}</p>}
                  </TableCell>
                  <TableCell className="hidden py-3 whitespace-nowrap xl:table-cell">
                    <span className="inline-flex items-center gap-1.5">
                      {t.priority && <PriorityChip priority={t.priority} />}
                      <SlaBadge badge={t.sla} />
                    </span>
                  </TableCell>
                  <TableCell className="num hidden py-3 text-right text-xs whitespace-nowrap text-muted-foreground lg:table-cell" title={dateTime(t.created_at)}>
                    {relativeTime(t.created_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {pages > 1 && (
            <footer className="flex items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-sm">
              <span className="text-muted-foreground">
                Page <span className="num">{page}</span> of <span className="num">{pages}</span>
              </span>
              <span className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  Previous
                </Button>
                <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                  Next
                </Button>
              </span>
            </footer>
          )}
        </Card>
      )}
    </Page>
  );
}
