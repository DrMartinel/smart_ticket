"use client";

// Teams (F2 · Teams 9-646): which team owns each category, its strategy, cap and members.

import { useCallback, useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { TeamDetailOut, TeamOut, TeamStrategy, TicketCategory } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { NativeSelect } from "@/components/ui/native-select";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";

const CATEGORIES: TicketCategory[] = ["hardware", "software", "network", "access", "security", "other"];

interface Draft {
  slug: string;
  name: string;
  categories: TicketCategory[];
  strategy: TeamStrategy;
  max_open_per_member: string;
  keycloak_group: string;
  is_fallback: boolean;
  is_active: boolean;
  reason: string;
}

const BLANK: Draft = {
  slug: "",
  name: "",
  categories: [],
  strategy: "least_loaded",
  max_open_per_member: "",
  keycloak_group: "",
  is_fallback: false,
  is_active: true,
  reason: "",
};

function draftOf(team: TeamOut): Draft {
  return {
    slug: team.slug,
    name: team.name,
    categories: team.categories as TicketCategory[],
    strategy: team.strategy as TeamStrategy,
    max_open_per_member: team.max_open_per_member ? String(team.max_open_per_member) : "",
    keycloak_group: team.keycloak_group ?? "",
    is_fallback: team.is_fallback,
    is_active: team.is_active,
    reason: "",
  };
}

export default function TeamsPage() {
  const user = useRequireAuth();
  const [teams, setTeams] = useState<TeamOut[] | null>(null);
  const [editing, setEditing] = useState<{ draft: Draft; create: boolean } | null>(null);
  const [detail, setDetail] = useState<TeamDetailOut | null>(null);
  const [taken, setTaken] = useState<{ category: string; team: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newMember, setNewMember] = useState({ username: "", role: "member" });

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

  const open = async (team: TeamOut | null) => {
    setError(null);
    setTaken(null);
    setEditing({ draft: team ? draftOf(team) : BLANK, create: !team });
    setDetail(team ? await api.get<TeamDetailOut>(`/api/teams/${team.slug}`).catch(() => null) : null);
  };

  const save = async (move = false) => {
    if (!editing) return;
    const d = editing.draft;
    setError(null);
    const body = {
      name: d.name,
      categories: d.categories,
      strategy: d.strategy,
      max_open_per_member: d.max_open_per_member ? Number(d.max_open_per_member) : null,
      keycloak_group: d.keycloak_group || null,
      is_fallback: d.is_fallback,
      move_categories: move,
      reason: d.reason,
      ...(editing.create ? { slug: d.slug } : { is_active: d.is_active }),
    };
    try {
      if (editing.create) await api.post("/api/teams", body);
      else await api.patch(`/api/teams/${d.slug}`, body);
      setEditing(null);
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.code === "category_taken") {
        setTaken(err.details as { category: string; team: string });
        return;
      }
      setError(err instanceof ApiError ? err.message : "Couldn't save the team.");
    }
  };

  const addMember = async () => {
    if (!editing || !newMember.username) return;
    setError(null);
    try {
      await api.post(`/api/teams/${editing.draft.slug}/members`, newMember);
      setNewMember({ username: "", role: "member" });
      setDetail(await api.get<TeamDetailOut>(`/api/teams/${editing.draft.slug}`));
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't add the member.");
    }
  };

  const removeMember = async (username: string) => {
    if (!editing) return;
    try {
      await api.delete(`/api/teams/${editing.draft.slug}/members/${encodeURIComponent(username)}`);
      setDetail(await api.get<TeamDetailOut>(`/api/teams/${editing.draft.slug}`));
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove the member.");
    }
  };

  const set = (patch: Partial<Draft>) => editing && setEditing({ ...editing, draft: { ...editing.draft, ...patch } });
  const d = editing?.draft;

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Teams</h1>
          <p className="text-xs text-muted-foreground">
            Each category is owned by exactly one active team. Company sign-in users get their teams from Keycloak groups.
          </p>
        </div>
        {canEdit && (
          <Button onClick={() => void open(null)}>
            New team
          </Button>
        )}
      </header>

      {error && !editing && <p className="text-sm text-danger">{error}</p>}

      <Card className="overflow-x-auto">
        <Table className="w-full min-w-[860px] text-left text-sm">
          <TableHeader className="bg-background text-[11px] text-muted-foreground">
            <TableRow>
              <TableHead className="px-4 py-2 font-normal">Team</TableHead>
              <TableHead className="px-4 py-2 font-normal">Categories</TableHead>
              <TableHead className="px-4 py-2 font-normal">Strategy</TableHead>
              <TableHead className="px-4 py-2 font-normal">Cap</TableHead>
              <TableHead className="px-4 py-2 font-normal">Members</TableHead>
              <TableHead className="px-4 py-2 font-normal">Lead</TableHead>
              <TableHead className="px-4 py-2 font-normal">Keycloak group</TableHead>
              <TableHead className="px-4 py-2 font-normal" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {teams?.map((t) => (
              <TableRow key={t.slug} className={`border-t border-border ${t.is_active ? "" : "text-muted-foreground"}`}>
                <TableCell className="px-4 py-2.5">
                  {canEdit ? (
                    <Button variant="link" size="inline"  onClick={() => void open(t)}>
                      {t.name}
                    </Button>
                  ) : (
                    t.name
                  )}
                </TableCell>
                <TableCell className="px-4 py-2.5">
                  <span className="flex flex-wrap gap-1">
                    {t.categories.map((c) => (
                      <Badge variant="neutral" key={c}>
                        {c}
                      </Badge>
                    ))}
                  </span>
                </TableCell>
                <TableCell className="px-4 py-2.5">{t.strategy}</TableCell>
                <TableCell className="px-4 py-2.5">{t.max_open_per_member ?? "—"}</TableCell>
                <TableCell className="px-4 py-2.5">{t.members_count}</TableCell>
                <TableCell className="px-4 py-2.5">{t.leads.join(", ") || "—"}</TableCell>
                <TableCell className="px-4 py-2.5 font-mono text-xs">{t.keycloak_group ?? "—"}</TableCell>
                <TableCell className="px-4 py-2.5">
                  {t.is_fallback && <Badge variant="info">fallback</Badge>}
                  {!t.is_active && <Badge variant="neutral">inactive</Badge>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <Modal
        open={!!editing}
        onClose={() => setEditing(null)}
        title={editing?.create ? "New team" : `Edit ${d?.name ?? ""}`}
        subtitle="Every save needs a reason and is recorded in the audit log."
        width="max-w-2xl"
        footer={
          <>
            <Button variant="outline" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button disabled={!d?.reason.trim() || !d?.name || !d?.slug} onClick={() => void save()}>
              Save
            </Button>
          </>
        }
      >
        {d && (
          <div className="flex flex-col gap-3 text-sm">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Name</span>
                <Input value={d.name} onChange={(e) => set({ name: e.target.value })} />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Slug</span>
                <Input
                  className="font-mono"
                  value={d.slug}
                  disabled={!editing?.create}
                  onChange={(e) => set({ slug: e.target.value.toLowerCase() })}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Strategy</span>
                <NativeSelect value={d.strategy} onChange={(e) => set({ strategy: e.target.value as TeamStrategy })}>
                  <option value="least_loaded">least_loaded: fewest open tickets</option>
                  <option value="round_robin">round_robin: assigned longest ago</option>
                </NativeSelect>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Cap (open tickets per member)</span>
                <Input
                  type="number"
                  min={1}
                  value={d.max_open_per_member}
                  onChange={(e) => set({ max_open_per_member: e.target.value })}
                  placeholder="none"
                />
              </label>
              <label className="flex flex-col gap-1 sm:col-span-2">
                <span className="text-xs text-muted-foreground">Keycloak group</span>
                <Input className="font-mono" value={d.keycloak_group} onChange={(e) => set({ keycloak_group: e.target.value })} />
              </label>
            </div>
            <fieldset className="flex flex-wrap gap-x-4 gap-y-1.5">
              <legend className="pb-1 text-xs text-muted-foreground">Categories it owns</legend>
              {CATEGORIES.map((c) => (
                <label key={c} className="flex items-center gap-1.5">
                  <Checkbox
                    checked={d.categories.includes(c)}
                    onCheckedChange={() =>
                      set({ categories: d.categories.includes(c) ? d.categories.filter((x) => x !== c) : [...d.categories, c] })
                    }
                  />
                  {c}
                </label>
              ))}
            </fieldset>
            <div className="flex flex-wrap gap-4">
              <label className="flex items-center gap-1.5">
                <Checkbox checked={d.is_fallback} onCheckedChange={(checked) => set({ is_fallback: checked === true })} />
                Fallback team (gets tickets whose category no team owns)
              </label>
              {!editing?.create && (
                <label className="flex items-center gap-1.5">
                  <Checkbox checked={d.is_active} onCheckedChange={(checked) => set({ is_active: checked === true })} />
                  Active
                </label>
              )}
            </div>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Reason</span>
              <Input value={d.reason} maxLength={500} onChange={(e) => set({ reason: e.target.value })} />
            </label>

            {taken && (
              <div className="flex flex-wrap items-center gap-3 rounded-md bg-warn-soft px-3 py-2 text-warn">
                <span>
                  {taken.category} belongs to team {taken.team}.
                </span>
                <Button variant="outline" onClick={() => void save(true)}>
                  Move it here
                </Button>
              </div>
            )}
            {error && <p className="rounded-md bg-danger-soft px-3 py-2 text-danger">{error}</p>}

            {detail && (
              <div className="flex flex-col gap-2 border-t border-border pt-3">
                <p className="text-xs text-muted-foreground">Members (Keycloak-managed members change through their groups)</p>
                <ul className="flex flex-col gap-1">
                  {detail.members.map((m) => (
                    <li key={m.username} className="flex items-center justify-between gap-3">
                      <span>
                        {m.username} · {m.role}
                        {!m.is_available && " · unavailable"} · <span className="text-muted-foreground">{m.source}</span>
                      </span>
                      {m.source === "local" && (
                        <Button variant="link" size="inline" className="text-xs text-danger" onClick={() => void removeMember(m.username)}>
                          Remove
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
                <div className="flex flex-wrap items-end gap-2">
                  <Input
                    placeholder="username (local account)"
                    value={newMember.username}
                    onChange={(e) => setNewMember({ ...newMember, username: e.target.value })}
                  />
                  <NativeSelect value={newMember.role} onChange={(e) => setNewMember({ ...newMember, role: e.target.value })}>
                    <option value="member">member</option>
                    <option value="lead">lead</option>
                  </NativeSelect>
                  <Button variant="outline" onClick={() => void addMember()}>
                    Add member
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
