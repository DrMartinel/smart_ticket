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
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

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
          <p className="text-xs text-muted-foreground">
            Strategy {team?.strategy ?? "—"} · cap {team?.max_open_per_member ?? "none"} open per member. Going unavailable or on
            leave moves nothing.{" "}
            <Link href={`/teams/${slug}`} className="text-primary hover:underline">
              Team queue
            </Link>
          </p>
        </div>
        <TeamPicker teams={teams} value={slug} onChange={(next) => router.push(`/teams/${next}/workload`)} />
      </header>

      {error && <p className="text-sm text-danger">{error}</p>}

      <Card className="overflow-x-auto">
        <Table className="w-full min-w-[860px] text-left text-sm">
          <TableHeader className="bg-background text-[11px] text-muted-foreground">
            <TableRow>
              <TableHead className="px-4 py-2 font-normal">Member</TableHead>
              <TableHead className="px-4 py-2 font-normal">Role</TableHead>
              <TableHead className="px-4 py-2 font-normal">Available</TableHead>
              <TableHead className="px-4 py-2 font-normal">Leave</TableHead>
              <TableHead className="px-4 py-2 font-normal">Open / cap</TableHead>
              <TableHead className="px-4 py-2 font-normal">Oldest SLA due</TableHead>
              <TableHead className="px-4 py-2 font-normal">Last assigned</TableHead>
              <TableHead className="px-4 py-2 font-normal" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows?.map((r) => (
              <TableRow key={r.user} className={`border-t border-border ${r.flagged ? "bg-warn-soft" : ""}`}>
                <TableCell className="px-4 py-2.5">{r.user}</TableCell>
                <TableCell className="px-4 py-2.5">{r.role}</TableCell>
                <TableCell className="px-4 py-2.5">
                  <Switch
                    checked={r.available}
                    disabled={!canEdit}
                    label={`${r.user} available`}
                    onChange={(next) => void setAvailable(r.user, next)}
                  />
                </TableCell>
                <TableCell className="px-4 py-2.5">{r.on_leave ? <Badge variant="warn">On leave today</Badge> : "—"}</TableCell>
                <TableCell className="px-4 py-2.5 tabular-nums">
                  {r.open} / {r.cap ?? "—"}
                </TableCell>
                <TableCell className="whitespace-nowrap px-4 py-2.5">{dateTime(r.oldest_due)}</TableCell>
                <TableCell className="whitespace-nowrap px-4 py-2.5">{dateTime(r.last_assigned_at)}</TableCell>
                <TableCell className="px-4 py-2.5">
                  {r.flagged ? (
                    <span className="text-warn">
                      {r.open} ticket{r.open === 1 ? "" : "s"} still assigned
                    </span>
                  ) : r.next_pick ? (
                    <span className="text-ok">Next pick</span>
                  ) : !r.available ? (
                    <span className="text-muted-foreground">Skipped: unavailable</span>
                  ) : r.on_leave ? (
                    <span className="text-muted-foreground">Skipped: leave</span>
                  ) : (
                    "—"
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
      <p className="text-[11px] text-muted-foreground">
        Reassign a flagged person&apos;s tickets one by one from the team queue or the ticket page.
      </p>
    </div>
  );
}
