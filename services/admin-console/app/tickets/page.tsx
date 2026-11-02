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
import type { StaffTicketPage, StaffTicketRow } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

type TicketRow = StaffTicketRow;
type TicketPage = StaffTicketPage;

const PAGE_SIZE = 50;

const EMPTY: Record<string, string> = {
  review: "Nothing is waiting for review.",
  mine: "No open tickets are assigned to you.",
  open: "No open tickets.",
  resolved: "No resolved tickets yet.",
  all: "No tickets yet.",
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
      .catch(() => current && setError("Couldn't load tickets. Is core-api running?"));
    return () => {
      current = false;
    };
  }, [user, view, page, submitted]);

  if (!user) return null;

  const title = VIEWS.find((v) => v.key === view)?.label ?? "Tickets";
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="mx-auto max-w-[1280px]">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {data ? `${data.total} ticket${data.total === 1 ? "" : "s"}` : "Loading…"}
          </p>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setSubmitted(query.trim());
          }}
          className="flex gap-2"
        >
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by ticket ID or subject"
            aria-label="Search tickets"
            className="w-72"
          />
          <Button variant="outline" type="submit">
            Search
          </Button>
        </form>
      </header>

      {error && <p className="text-sm text-danger">{error}</p>}

      {data && data.items.length === 0 && (
        <Card className="px-6 py-12 text-center text-sm text-muted-foreground">
          {submitted ? `No tickets match "${submitted}".` : EMPTY[view] ?? "No tickets."}
        </Card>
      )}

      {data && data.items.length > 0 && (
        <Card className="overflow-x-auto">
          <Table className="w-full min-w-[640px] table-fixed text-sm">
            <TableHeader className="bg-muted text-left text-xs font-medium text-muted-foreground">
              <TableRow>
                <TableHead className="px-4 py-2.5 font-medium">Ticket</TableHead>
                <TableHead className="w-44 px-4 py-2.5 font-medium">Status</TableHead>
                <TableHead className="w-52 px-4 py-2.5 font-medium">Needs</TableHead>
                <TableHead className="hidden w-40 px-4 py-2.5 font-medium xl:table-cell">Owner</TableHead>
                <TableHead className="hidden w-56 px-4 py-2.5 font-medium xl:table-cell">SLA</TableHead>
                <TableHead className="hidden w-28 px-4 py-2.5 text-right font-medium lg:table-cell">Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((t) => (
                <TableRow
                  key={t.public_id}
                  onClick={() => router.push(`/tickets/${t.public_id}`)}
                  className="cursor-pointer border-t border-border align-top hover:bg-muted"
                >
                  <TableCell className="px-4 py-3">
                    <a
                      href={`/tickets/${t.public_id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="block truncate font-medium hover:text-primary"
                    >
                      {t.subject_masked}
                    </a>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      <span className="font-mono">{t.public_id}</span> · {t.reporter} · {humanize(t.source)}
                      {t.category && ` · ${t.category}`}
                    </p>
                  </TableCell>
                  <TableCell className="px-4 py-3">
                    <StatusChip name={t.status.name} color={t.status.color} />
                  </TableCell>
                  <TableCell className="px-4 py-3">
                    {t.review ? (
                      <span className="inline-flex items-center gap-2">
                        <Badge variant={priorityTone(t.review.priority)}>P{t.review.priority}</Badge>
                        <span className="whitespace-nowrap">{QUEUE_LABEL[t.review.queue] ?? humanize(t.review.queue)}</span>
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="hidden whitespace-nowrap px-4 py-3 xl:table-cell">
                    {t.assignee ?? <span className="text-muted-foreground">Unassigned</span>}
                    {t.assigned_team && <p className="text-xs text-muted-foreground">{t.assigned_team}</p>}
                  </TableCell>
                  <TableCell className="hidden whitespace-nowrap px-4 py-3 xl:table-cell">
                    <span className="inline-flex items-center gap-1.5">
                      {t.priority && <PriorityChip priority={t.priority} />}
                      <SlaBadge badge={t.sla} />
                    </span>
                  </TableCell>
                  <TableCell className="hidden whitespace-nowrap px-4 py-3 text-right text-muted-foreground lg:table-cell" title={dateTime(t.created_at)}>
                    {relativeTime(t.created_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {pages > 1 && (
            <footer className="flex items-center justify-between border-t border-border px-4 py-2.5 text-sm">
              <span className="text-muted-foreground">
                Page {page} of {pages}
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
    </div>
  );
}
