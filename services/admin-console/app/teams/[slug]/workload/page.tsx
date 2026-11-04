"use client";

import { Users } from "lucide-react";
import { TabNav } from "@/components/TabNav";
import { STRATEGY_LABEL } from "@/components/teams/TeamForm";
import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, TableStatus } from "@/components/ui/states";

// Team workload (F2 · Team workload 9-450): each member's load, availability and leave.

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
    <Page className="flex flex-col gap-4">
      <PageHeader
        className="mb-0"
        eyebrow="Workspace / Teams"
        title={`${team?.name ?? slug} workload`}
        description={
          <>
            Assignment: {team ? (STRATEGY_LABEL[team.strategy] ?? team.strategy).toLowerCase() : "—"} · cap{" "}
            <span className="num">{team?.max_open_per_member ?? "none"}</span> open per member. Going unavailable or on leave doesn&apos;t move
            anyone&apos;s tickets.
          </>
        }
        actions={<TeamPicker teams={teams} value={slug} onChange={(next) => router.push(`/teams/${next}/workload`)} />}
      />
      <TabNav
        className="mb-1"
        tabs={[
          { href: `/teams/${slug}`, label: "Queue", active: false },
          { href: `/teams/${slug}/workload`, label: "Workload", active: true },
        ]}
      />

      {error && <ErrorState title={error} onRetry={error.startsWith("Couldn't load") ? () => void load() : undefined} />}

      <Card className="overflow-x-auto">
        <Table className="min-w-[860px]">
          <TableHeader>
            <TableRow>
              <TableHead>Member</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Available</TableHead>
              <TableHead>Leave</TableHead>
              <TableHead>Open / cap</TableHead>
              <TableHead>Oldest SLA due</TableHead>
              <TableHead>Last assigned</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows?.map((r) => (
              <TableRow key={r.user} className={r.flagged ? "bg-warn-soft/60" : ""}>
                <TableCell>{r.user}</TableCell>
                <TableCell>{r.role}</TableCell>
                <TableCell>
                  <Switch
                    checked={r.available}
                    disabled={!canEdit}
                    label={`${r.user} available`}
                    onChange={(next) => void setAvailable(r.user, next)}
                  />
                </TableCell>
                <TableCell>{r.on_leave ? <Badge variant="warn">On leave today</Badge> : "—"}</TableCell>
                <TableCell className="num">
                  {r.open} / {r.cap ?? "—"}
                </TableCell>
                <TableCell className="num whitespace-nowrap text-xs">{dateTime(r.oldest_due)}</TableCell>
                <TableCell className="num whitespace-nowrap text-xs">{dateTime(r.last_assigned_at)}</TableCell>
                <TableCell>
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
            <TableStatus
              colSpan={8}
              rows={rows}
              error={!!error}
              empty={<EmptyState compact icon={Users} title="No members yet">Members are added on the team&apos;s settings page.</EmptyState>}
            />
          </TableBody>
        </Table>
      </Card>
      <p className="text-xs text-muted-foreground">
        Reassign a flagged person&apos;s tickets one by one from the team queue or the ticket page.
      </p>
    </Page>
  );
}
