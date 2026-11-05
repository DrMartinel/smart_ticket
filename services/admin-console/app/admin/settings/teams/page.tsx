"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, TableStatus } from "@/components/ui/states";

// Teams (F2 · Teams 9-646): every team, the categories it owns and its members; a new team opens on its own page.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { SectionTabs } from "@/components/TabNav";
import { BLANK_TEAM, STRATEGY_LABEL, TeamForm, bodyOf, type TeamDraft } from "@/components/teams/TeamForm";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { TeamDetailOut, TeamOut } from "@/lib/types/generated";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export default function TeamsPage() {
  const user = useRequireAuth();
  const router = useRouter();
  const [teams, setTeams] = useState<TeamOut[] | null>(null);
  const [draft, setDraft] = useState<TeamDraft | null>(null);
  const [taken, setTaken] = useState<{ category: string; team: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setTeams(await api.get<TeamOut[]>("/api/teams"));
    } catch {
      setError("Couldn't load the teams.");
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;
  const canEdit = user.role === "manager" || (user.capabilities ?? []).includes("workflow_admin");

  const create = async (move = false) => {
    if (!draft) return;
    setError(null);
    try {
      const created = await api.post<TeamDetailOut>("/api/teams", bodyOf(draft, true, move));
      router.push(`/admin/settings/teams/${created.slug}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "category_taken") {
        setTaken(err.details as { category: string; team: string });
        return;
      }
      setError(err instanceof ApiError ? err.message : "Couldn't create the team.");
    }
  };

  const active = teams?.filter((t) => t.is_active).length ?? 0;
  const members = teams?.reduce((n, t) => n + t.members_count, 0) ?? 0;

  return (
    <Page width="record" className="flex flex-col gap-4">
      <SectionTabs className="mb-1" />
      <PageHeader
        className="mb-2"
        eyebrow="Admin / People & access"
        title="Teams"
        description={<>{teams ? `${active} active teams · ${members} memberships. ` : ""}Each category belongs to exactly one active team.</>}
        actions={
      <>
      {canEdit && (
        <Button
          onClick={() => {
            setDraft({ ...BLANK_TEAM });
            setTaken(null);
            setError(null);
          }}
        >
          New team
        </Button>
      )}
      </>
      }
      />

      {error && !draft && <ErrorState title={error} onRetry={() => { setError(null); void load(); }} />}

      <Card className="overflow-x-auto">
        <Table className="min-w-[820px]">
          <TableHeader>
            <TableRow>
              <TableHead>Team</TableHead>
              <TableHead>Categories</TableHead>
              <TableHead>Who gets the next ticket</TableHead>
              <TableHead>Members</TableHead>
              <TableHead>Leads</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableStatus colSpan={6} rows={teams} error={!!error} empty={<EmptyState compact title="No teams yet" />} />
            {teams?.map((t) => (
              <TableRow key={t.slug} className={`${t.is_active ? "" : "text-muted-foreground"}`}>
                <TableCell>
                  <Link href={`/admin/settings/teams/${t.slug}`} className="font-medium text-primary hover:underline">
                    {t.name}
                  </Link>
                  <span className="block font-mono text-[11px] text-muted-foreground">{t.slug}</span>
                </TableCell>
                <TableCell>
                  <span className="flex flex-wrap gap-1">
                    {t.categories.length === 0 && <span className="text-muted-foreground">—</span>}
                    {t.categories.map((c) => (
                      <Badge variant="neutral" key={c}>
                        {c}
                      </Badge>
                    ))}
                  </span>
                </TableCell>
                <TableCell>
                  {STRATEGY_LABEL[t.strategy] ?? t.strategy}
                  {t.max_open_per_member ? <span className="text-muted-foreground"> · cap {t.max_open_per_member}</span> : null}
                </TableCell>
                <TableCell className="tabular-nums">{t.members_count}</TableCell>
                <TableCell>{t.leads.join(", ") || <span className="text-muted-foreground">—</span>}</TableCell>
                <TableCell>
                  <span className="flex flex-wrap justify-end gap-1">
                    {t.is_fallback && <Badge variant="info">fallback</Badge>}
                    {!t.is_active && <Badge variant="neutral">inactive</Badge>}
                  </span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <Modal
        open={!!draft}
        onClose={() => setDraft(null)}
        title="New team"
        subtitle="You add members on the team's page once it exists."
        size="xl"
        footer={
          <>
            <Button variant="outline" onClick={() => setDraft(null)}>
              Cancel
            </Button>
            <Button disabled={!draft?.reason.trim() || !draft?.name || !draft?.slug} onClick={() => void create()}>
              Create team
            </Button>
          </>
        }
      >
        {draft && (
          <div className="flex flex-col gap-3">
            <TeamForm draft={draft} create onChange={(patch) => setDraft({ ...draft, ...patch })} />
            {taken && (
              <div className="flex flex-wrap items-center gap-3 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
                <span>
                  {taken.category} belongs to team {taken.team}.
                </span>
                <Button variant="outline" onClick={() => void create(true)}>
                  Move it to the new team
                </Button>
              </div>
            )}
            {error && <ErrorState compact title="The team wasn't created">{error}</ErrorState>}
          </div>
        )}
      </Modal>
    </Page>
  );
}
