"use client";

// The team queue (F2 · Team queue 9-237): unowned tickets first, then the earliest due.

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import StatusChip from "@/components/StatusChip";
import TeamPicker, { useVisibleTeams } from "@/components/TeamPicker";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { dateTime, relativeTime } from "@/lib/format";
import type { StaffTicketRow } from "@/lib/types/generated";

interface Page {
  items: StaffTicketRow[];
  count: number;
}

const LIMIT = 100;

export default function TeamQueuePage() {
  const user = useRequireAuth();
  const router = useRouter();
  const slug = String(useParams().slug ?? "");
  const teams = useVisibleTeams(user);
  const [unassigned, setUnassigned] = useState(false);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setPage(await api.get<Page>(`/api/teams/${encodeURIComponent(slug)}/queue?limit=${LIMIT}&unassigned=${unassigned}`));
    } catch (err) {
      setPage(null);
      setError(err instanceof ApiError && err.code === "not_a_member" ? "You're not in this team." : "Couldn't load the queue.");
    }
  }, [slug, unassigned]);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;

  const take = async (row: StaffTicketRow) => {
    setNotice(null);
    try {
      await api.post(`/api/tickets/${encodeURIComponent(row.public_id)}/take`, { expected_version: row.version });
      setNotice(`You have ${row.public_id}.`);
    } catch (err) {
      setNotice(
        err instanceof ApiError && err.code === "already_assigned"
          ? `Đã có người nhận · Someone took ${row.public_id} a moment ago.`
          : `Couldn't take ${row.public_id}.`,
      );
    }
    await load();
  };

  const team = teams.find((t) => t.slug === slug);

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{team?.name ?? slug} team queue</h1>
          <p className="text-xs text-[var(--text-muted)]">
            Unassigned first, then earliest SLA due. Members take tickets; the lead assigns and reassigns.{" "}
            <Link href={`/teams/${slug}/workload`} className="text-[var(--accent)] hover:underline">
              Workload
            </Link>
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <TeamPicker teams={teams} value={slug} onChange={(next) => router.push(`/teams/${next}`)} />
          <label className="flex items-center gap-2 pb-2 text-sm">
            <input type="checkbox" checked={unassigned} onChange={(e) => setUnassigned(e.target.checked)} />
            Unassigned only
          </label>
        </div>
      </header>

      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
      {notice && <p className="text-sm text-[var(--text-muted)]">{notice}</p>}

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[820px] text-left text-sm">
          <thead className="bg-[var(--bg)] text-[11px] text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2 font-normal">Ticket</th>
              <th className="px-4 py-2 font-normal">Subject</th>
              <th className="px-4 py-2 font-normal">Assignee</th>
              <th className="px-4 py-2 font-normal">Status</th>
              <th className="px-4 py-2 font-normal">SLA due</th>
              <th className="px-4 py-2 font-normal" />
            </tr>
          </thead>
          <tbody>
            {page?.items.map((row) => (
              <tr key={row.public_id} className={`border-t border-[var(--border)] ${row.assignee ? "" : "bg-[var(--surface-2)]"}`}>
                <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs">
                  <Link href={`/tickets/${row.public_id}`} className="hover:underline">
                    {row.public_id}
                  </Link>
                </td>
                <td className="max-w-[360px] px-4 py-2.5">{row.subject_masked}</td>
                <td className="px-4 py-2.5">{row.assignee ?? <span className="text-[var(--text-muted)]">Unassigned</span>}</td>
                <td className="px-4 py-2.5">
                  <StatusChip name={row.status.name} color={row.status.color} />
                </td>
                <td className="whitespace-nowrap px-4 py-2.5" title={dateTime(row.sla_due_at)}>
                  {row.sla_due_at ? relativeTime(row.sla_due_at) : "—"}
                </td>
                <td className="px-4 py-2.5 text-right">
                  {!row.assignee ? (
                    <button className="btn btn-primary" onClick={() => void take(row)}>
                      Take
                    </button>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
            {page && page.items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-[var(--text-muted)]">
                  Nothing in this queue.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-[var(--text-muted)]">Priority and SLA badges arrive with F1.</p>
    </div>
  );
}
