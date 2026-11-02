"use client";

// Team workload (F2 · Team workload 9-450): each member's load, availability and leave.

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Switch from "@/components/Switch";
import TeamPicker, { useVisibleTeams } from "@/components/TeamPicker";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { dateTime } from "@/lib/format";
import type { WorkloadRowOut } from "@/lib/types/generated";

export default function WorkloadPage() {
  const user = useRequireAuth();
  const router = useRouter();
  const slug = String(useParams().slug ?? "");
  const teams = useVisibleTeams(user);
  const [rows, setRows] = useState<WorkloadRowOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setRows(await api.get<WorkloadRowOut[]>(`/api/teams/${encodeURIComponent(slug)}/workload`));
    } catch (err) {
      setRows(null);
      setError(err instanceof ApiError && err.code === "not_a_member" ? "You're not in this team." : "Couldn't load the workload.");
    }
  }, [slug]);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;

  const team = teams.find((t) => t.slug === slug);
  const canEdit = user.role === "manager" || (user.teams ?? []).some((t) => t.team === slug && t.role === "lead");

  const setAvailable = async (member: string, available: boolean) => {
    setError(null);
    try {
      await api.put(`/api/teams/${encodeURIComponent(slug)}/members/${encodeURIComponent(member)}/availability`, {
        is_available: available,
      });
    } catch {
      setError(`Couldn't change ${member}'s availability.`);
    }
    await load();
  };

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{team?.name ?? slug} workload</h1>
          <p className="text-xs text-[var(--text-muted)]">
            Strategy {team?.strategy ?? "—"} · cap {team?.max_open_per_member ?? "none"} open per member. Going unavailable or on
            leave moves nothing.{" "}
            <Link href={`/teams/${slug}`} className="text-[var(--accent)] hover:underline">
              Team queue
            </Link>
          </p>
        </div>
        <TeamPicker teams={teams} value={slug} onChange={(next) => router.push(`/teams/${next}/workload`)} />
      </header>

      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead className="bg-[var(--bg)] text-[11px] text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2 font-normal">Member</th>
              <th className="px-4 py-2 font-normal">Role</th>
              <th className="px-4 py-2 font-normal">Available</th>
              <th className="px-4 py-2 font-normal">Leave</th>
              <th className="px-4 py-2 font-normal">Open / cap</th>
              <th className="px-4 py-2 font-normal">Oldest SLA due</th>
              <th className="px-4 py-2 font-normal">Last assigned</th>
              <th className="px-4 py-2 font-normal" />
            </tr>
          </thead>
          <tbody>
            {rows?.map((r) => (
              <tr key={r.user} className={`border-t border-[var(--border)] ${r.flagged ? "bg-[var(--warn-soft)]" : ""}`}>
                <td className="px-4 py-2.5">{r.user}</td>
                <td className="px-4 py-2.5">{r.role}</td>
                <td className="px-4 py-2.5">
                  <Switch
                    checked={r.available}
                    disabled={!canEdit}
                    label={`${r.user} available`}
                    onChange={(next) => void setAvailable(r.user, next)}
                  />
                </td>
                <td className="px-4 py-2.5">{r.on_leave ? <span className="badge tone-warn">On leave today</span> : "—"}</td>
                <td className="px-4 py-2.5 tabular-nums">
                  {r.open} / {r.cap ?? "—"}
                </td>
                <td className="whitespace-nowrap px-4 py-2.5">{dateTime(r.oldest_due)}</td>
                <td className="whitespace-nowrap px-4 py-2.5">{dateTime(r.last_assigned_at)}</td>
                <td className="px-4 py-2.5">
                  {r.flagged ? (
                    <span className="text-[var(--warn)]">
                      {r.open} ticket{r.open === 1 ? "" : "s"} still assigned
                    </span>
                  ) : r.next_pick ? (
                    <span className="text-[var(--ok)]">Next pick</span>
                  ) : !r.available ? (
                    <span className="text-[var(--text-muted)]">Skipped: unavailable</span>
                  ) : r.on_leave ? (
                    <span className="text-[var(--text-muted)]">Skipped: leave</span>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-[var(--text-muted)]">
        Reassign a flagged person&apos;s tickets one by one from the team queue or the ticket page.
      </p>
    </div>
  );
}
