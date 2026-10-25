"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useRequireAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { QUEUE_LABEL } from "@/lib/explain";
import { dateTime, humanize, relativeTime } from "@/lib/format";
import { VIEWS } from "@/lib/views";
import StatusChip from "@/components/StatusChip";
import { priorityClasses } from "@/lib/badges";
import type { StaffTicketPage, StaffTicketRow } from "@/lib/types/generated";

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
          <p className="mt-0.5 text-sm text-[var(--text-muted)]">
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
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by ticket ID or subject"
            aria-label="Search tickets"
            className="field w-72"
          />
          <button type="submit" className="btn btn-secondary">
            Search
          </button>
        </form>
      </header>

      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}

      {data && data.items.length === 0 && (
        <div className="card px-6 py-12 text-center text-sm text-[var(--text-muted)]">
          {submitted ? `No tickets match "${submitted}".` : EMPTY[view] ?? "No tickets."}
        </div>
      )}

      {data && data.items.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[640px] table-fixed text-sm">
            <thead className="bg-[var(--surface-2)] text-left text-xs font-medium text-[var(--text-muted)]">
              <tr>
                <th className="px-4 py-2.5 font-medium">Ticket</th>
                <th className="w-44 px-4 py-2.5 font-medium">Status</th>
                <th className="w-52 px-4 py-2.5 font-medium">Needs</th>
                <th className="hidden w-40 px-4 py-2.5 font-medium xl:table-cell">Owner</th>
                <th className="hidden w-36 px-4 py-2.5 font-medium xl:table-cell">SLA</th>
                <th className="hidden w-28 px-4 py-2.5 text-right font-medium lg:table-cell">Created</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((t) => (
                <tr
                  key={t.public_id}
                  onClick={() => router.push(`/tickets/${t.public_id}`)}
                  className="cursor-pointer border-t border-[var(--border)] align-top hover:bg-[var(--surface-2)]"
                >
                  <td className="px-4 py-3">
                    <a
                      href={`/tickets/${t.public_id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="block truncate font-medium hover:text-[var(--accent)]"
                    >
                      {t.subject_masked}
                    </a>
                    <p className="mt-0.5 truncate text-xs text-[var(--text-muted)]">
                      <span className="font-mono">{t.public_id}</span> · {t.reporter} · {humanize(t.source)}
                      {t.category && ` · ${t.category}`}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <StatusChip name={t.status.name} color={t.status.color} />
                  </td>
                  <td className="px-4 py-3">
                    {t.review ? (
                      <span className="inline-flex items-center gap-2">
                        <span className={`badge ${priorityClasses(t.review.priority)}`}>P{t.review.priority}</span>
                        <span className="whitespace-nowrap">{QUEUE_LABEL[t.review.queue] ?? humanize(t.review.queue)}</span>
                      </span>
                    ) : (
                      <span className="text-[var(--text-muted)]">—</span>
                    )}
                  </td>
                  <td className="hidden whitespace-nowrap px-4 py-3 xl:table-cell">
                    {t.assignee ?? <span className="text-[var(--text-muted)]">Unassigned</span>}
                    {t.assigned_team && <p className="text-xs text-[var(--text-muted)]">{t.assigned_team}</p>}
                  </td>
                  <td className="hidden whitespace-nowrap px-4 py-3 xl:table-cell">
                    <SlaCell due={t.sla_due_at} done={t.status.is_completed} />
                  </td>
                  <td className="hidden whitespace-nowrap px-4 py-3 text-right text-[var(--text-muted)] lg:table-cell" title={dateTime(t.created_at)}>
                    {relativeTime(t.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {pages > 1 && (
            <footer className="flex items-center justify-between border-t border-[var(--border)] px-4 py-2.5 text-sm">
              <span className="text-[var(--text-muted)]">
                Page {page} of {pages}
              </span>
              <span className="flex gap-2">
                <button className="btn btn-secondary py-1" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  Previous
                </button>
                <button className="btn btn-secondary py-1" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                  Next
                </button>
              </span>
            </footer>
          )}
        </div>
      )}
    </div>
  );
}

function SlaCell({ due, done }: { due: string | null; done: boolean }) {
  if (!due) return <span className="text-[var(--text-muted)]">—</span>;
  if (done) return <span className="text-[var(--text-muted)]">Met</span>;
  const overdue = new Date(due).getTime() < Date.now();
  return (
    <span className={overdue ? "font-medium text-[var(--danger)]" : ""} title={dateTime(due)}>
      {overdue ? `Overdue ${relativeTime(due).replace(" ago", "")}` : `Due ${relativeTime(due)}`}
    </span>
  );
}
