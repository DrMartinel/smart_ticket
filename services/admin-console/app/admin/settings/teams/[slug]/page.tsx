"use client";

// One team (F2): its settings, and its members and leads.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { SectionTabs } from "@/components/TabNav";
import { TeamForm, bodyOf, draftOf, type TeamDraft } from "@/components/teams/TeamForm";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { AccountOut, TeamDetailOut } from "@/lib/types/generated";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const STAFF_ROLES = ["technician", "manager", "security"];

export default function TeamPage() {
  const user = useRequireAuth();
  const { slug } = useParams<{ slug: string }>();
  const [team, setTeam] = useState<TeamDetailOut | null>(null);
  const [people, setPeople] = useState<AccountOut[]>([]);
  const [draft, setDraft] = useState<TeamDraft | null>(null);
  const [taken, setTaken] = useState<{ category: string; team: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [adding, setAdding] = useState({ username: "", role: "member" });

  const load = useCallback(async () => {
    try {
      const t = await api.get<TeamDetailOut>(`/api/teams/${slug}`);
      setTeam(t);
      setDraft(draftOf(t));
      setPeople(await api.get<AccountOut[]>("/api/accounts/people").catch(() => []));
    } catch {
      setError("Couldn't load this team.");
    }
  }, [slug]);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;
  const canEdit = user.role === "manager" || (user.capabilities ?? []).includes("workflow_admin");
  const byName = new Map(people.map((p) => [p.username, p]));

  const save = async (move = false) => {
    if (!draft) return;
    setError(null);
    setSaved(false);
    try {
      const t = await api.patch<TeamDetailOut>(`/api/teams/${slug}`, bodyOf(draft, false, move));
      setTeam(t);
      setDraft(draftOf(t));
      setTaken(null);
      setSaved(true);
    } catch (err) {
      if (err instanceof ApiError && err.code === "category_taken") {
        setTaken(err.details as { category: string; team: string });
        return;
      }
      setError(err instanceof ApiError ? err.message : "Couldn't save the team.");
    }
  };

  const setMember = async (username: string, role: string) => {
    setError(null);
    try {
      await api.post(`/api/teams/${slug}/members`, { username, role });
      setAdding({ username: "", role: "member" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't change the member.");
    }
  };

  const removeMember = async (username: string) => {
    setError(null);
    try {
      await api.delete(`/api/teams/${slug}/members/${encodeURIComponent(username)}`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove the member.");
    }
  };

  const candidates = people.filter(
    (p) => p.is_active && STAFF_ROLES.includes(p.role) && !team?.members.some((m) => m.username === p.username),
  );

  return (
    <div className="mx-auto flex max-w-[1080px] flex-col gap-4">
      <SectionTabs className="mb-1" />
      <Link href="/admin/settings/teams" className="text-sm text-muted-foreground hover:text-foreground">
        ← All teams
      </Link>
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{team?.name ?? slug}</h1>
        {team?.is_fallback && <Badge variant="info">fallback</Badge>}
        {team && !team.is_active && <Badge variant="neutral">inactive</Badge>}
      </header>

      {error && <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-sm font-semibold">Members</h2>
          <span className="text-xs text-muted-foreground">
            {team ? `${team.members.length} ${team.members.length === 1 ? "person" : "people"}` : ""}
          </span>
        </div>
        <Table className="w-full text-left text-sm">
          <TableHeader className="bg-background text-[11px] text-muted-foreground">
            <TableRow>
              <TableHead className="px-5 py-2 font-normal">Person</TableHead>
              <TableHead className="px-5 py-2 font-normal">Account role</TableHead>
              <TableHead className="px-5 py-2 font-normal">In this team</TableHead>
              <TableHead className="px-5 py-2 font-normal">Taking tickets</TableHead>
              <TableHead className="px-5 py-2 font-normal" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {team?.members.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="px-5 py-6 text-center text-muted-foreground">
                  Nobody is in this team yet.
                </TableCell>
              </TableRow>
            )}
            {team?.members.map((m) => {
              const p = byName.get(m.username);
              return (
                <TableRow key={m.username} className="border-t border-border">
                  <TableCell className="px-5 py-2.5">
                    <span className="font-medium">{m.username}</span>
                    {p?.name && <span className="block text-xs text-muted-foreground">{p.name}</span>}
                  </TableCell>
                  <TableCell className="px-5 py-2.5 capitalize">{p?.role ?? "—"}</TableCell>
                  <TableCell className="px-5 py-2.5">
                    {canEdit ? (
                      <NativeSelect
                        size="sm"
                        wrapperClassName="w-28"
                        aria-label={`${m.username}'s role in the team`}
                        value={m.role}
                        onChange={(e) => void setMember(m.username, e.target.value)}
                      >
                        <option value="member">Member</option>
                        <option value="lead">Lead</option>
                      </NativeSelect>
                    ) : (
                      <span className="capitalize">{m.role}</span>
                    )}
                  </TableCell>
                  <TableCell className="px-5 py-2.5">
                    {m.is_available ? <Badge variant="ok">available</Badge> : <Badge variant="neutral">unavailable</Badge>}
                  </TableCell>
                  <TableCell className="px-5 py-2.5 text-right">
                    {canEdit && (
                      <Button variant="link" size="inline" className="text-xs text-danger" onClick={() => void removeMember(m.username)}>
                        Remove
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        {canEdit && (
          <div className="flex flex-wrap items-center gap-2 border-t border-border px-5 py-3">
            <NativeSelect
              wrapperClassName="min-w-[240px] flex-1"
              aria-label="Person to add"
              value={adding.username}
              onChange={(e) => setAdding({ ...adding, username: e.target.value })}
            >
              <option value="">Add a person…</option>
              {candidates.map((p) => (
                <option key={p.username} value={p.username}>
                  {p.username}
                  {p.name ? ` (${p.name})` : ""} · {p.role}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect
              wrapperClassName="w-32"
              aria-label="Role in the team"
              value={adding.role}
              onChange={(e) => setAdding({ ...adding, role: e.target.value })}
            >
              <option value="member">Member</option>
              <option value="lead">Lead</option>
            </NativeSelect>
            <Button variant="outline" disabled={!adding.username} onClick={() => void setMember(adding.username, adding.role)}>
              Add to team
            </Button>
          </div>
        )}
      </Card>

      <Card className="p-0">
        <div className="border-b border-border px-5 py-3">
          <h2 className="text-sm font-semibold">Settings</h2>
        </div>
        <div className="flex flex-col gap-3 px-5 py-4">
          {draft && <TeamForm draft={draft} create={false} disabled={!canEdit} onChange={(patch) => setDraft({ ...draft, ...patch })} />}
          {taken && (
            <div className="flex flex-wrap items-center gap-3 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
              <span>
                {taken.category} belongs to team {taken.team}.
              </span>
              <Button variant="outline" onClick={() => void save(true)}>
                Move it here
              </Button>
            </div>
          )}
          {canEdit && (
            <div className="flex items-center justify-end gap-3">
              {saved && <span className="text-xs text-muted-foreground">Saved.</span>}
              <Button disabled={!draft?.reason.trim() || !draft?.name} onClick={() => void save()}>
                Save settings
              </Button>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
