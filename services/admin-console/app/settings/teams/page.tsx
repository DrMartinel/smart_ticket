"use client";

// Teams (F2 · Teams 9-646): which team owns each category, its strategy, cap and members.

import { useCallback, useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { TeamDetailOut, TeamOut, TeamStrategy, TicketCategory } from "@/lib/types/generated";

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
          <p className="text-xs text-[var(--text-muted)]">
            Each category is owned by exactly one active team. Company sign-in users get their teams from Keycloak groups.
          </p>
        </div>
        {canEdit && (
          <button className="btn btn-primary" onClick={() => void open(null)}>
            New team
          </button>
        )}
      </header>

      {error && !editing && <p className="text-sm text-[var(--danger)]">{error}</p>}

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead className="bg-[var(--bg)] text-[11px] text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2 font-normal">Team</th>
              <th className="px-4 py-2 font-normal">Categories</th>
              <th className="px-4 py-2 font-normal">Strategy</th>
              <th className="px-4 py-2 font-normal">Cap</th>
              <th className="px-4 py-2 font-normal">Members</th>
              <th className="px-4 py-2 font-normal">Lead</th>
              <th className="px-4 py-2 font-normal">Keycloak group</th>
              <th className="px-4 py-2 font-normal" />
            </tr>
          </thead>
          <tbody>
            {teams?.map((t) => (
              <tr key={t.slug} className={`border-t border-[var(--border)] ${t.is_active ? "" : "text-[var(--text-muted)]"}`}>
                <td className="px-4 py-2.5">
                  {canEdit ? (
                    <button className="hover:underline" onClick={() => void open(t)}>
                      {t.name}
                    </button>
                  ) : (
                    t.name
                  )}
                </td>
                <td className="px-4 py-2.5">
                  <span className="flex flex-wrap gap-1">
                    {t.categories.map((c) => (
                      <span key={c} className="badge tone-neutral">
                        {c}
                      </span>
                    ))}
                  </span>
                </td>
                <td className="px-4 py-2.5">{t.strategy}</td>
                <td className="px-4 py-2.5">{t.max_open_per_member ?? "—"}</td>
                <td className="px-4 py-2.5">{t.members_count}</td>
                <td className="px-4 py-2.5">{t.leads.join(", ") || "—"}</td>
                <td className="px-4 py-2.5 font-mono text-xs">{t.keycloak_group ?? "—"}</td>
                <td className="px-4 py-2.5">
                  {t.is_fallback && <span className="badge tone-info">fallback</span>}
                  {!t.is_active && <span className="badge tone-neutral">inactive</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal
        open={!!editing}
        onClose={() => setEditing(null)}
        title={editing?.create ? "New team" : `Edit ${d?.name ?? ""}`}
        subtitle="Every save needs a reason and is recorded in the audit log."
        width="max-w-2xl"
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => setEditing(null)}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={!d?.reason.trim() || !d?.name || !d?.slug} onClick={() => void save()}>
              Save
            </button>
          </>
        }
      >
        {d && (
          <div className="flex flex-col gap-3 text-sm">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-[var(--text-muted)]">Name</span>
                <input className="field" value={d.name} onChange={(e) => set({ name: e.target.value })} />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-[var(--text-muted)]">Slug</span>
                <input
                  className="field font-mono"
                  value={d.slug}
                  disabled={!editing?.create}
                  onChange={(e) => set({ slug: e.target.value.toLowerCase() })}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-[var(--text-muted)]">Strategy</span>
                <select className="field" value={d.strategy} onChange={(e) => set({ strategy: e.target.value as TeamStrategy })}>
                  <option value="least_loaded">least_loaded: fewest open tickets</option>
                  <option value="round_robin">round_robin: assigned longest ago</option>
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-[var(--text-muted)]">Cap (open tickets per member)</span>
                <input
                  className="field"
                  type="number"
                  min={1}
                  value={d.max_open_per_member}
                  onChange={(e) => set({ max_open_per_member: e.target.value })}
                  placeholder="none"
                />
              </label>
              <label className="flex flex-col gap-1 sm:col-span-2">
                <span className="text-xs text-[var(--text-muted)]">Keycloak group</span>
                <input className="field font-mono" value={d.keycloak_group} onChange={(e) => set({ keycloak_group: e.target.value })} />
              </label>
            </div>
            <fieldset className="flex flex-wrap gap-x-4 gap-y-1.5">
              <legend className="pb-1 text-xs text-[var(--text-muted)]">Categories it owns</legend>
              {CATEGORIES.map((c) => (
                <label key={c} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={d.categories.includes(c)}
                    onChange={() =>
                      set({ categories: d.categories.includes(c) ? d.categories.filter((x) => x !== c) : [...d.categories, c] })
                    }
                  />
                  {c}
                </label>
              ))}
            </fieldset>
            <div className="flex flex-wrap gap-4">
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={d.is_fallback} onChange={(e) => set({ is_fallback: e.target.checked })} />
                Fallback team (gets tickets whose category no team owns)
              </label>
              {!editing?.create && (
                <label className="flex items-center gap-1.5">
                  <input type="checkbox" checked={d.is_active} onChange={(e) => set({ is_active: e.target.checked })} />
                  Active
                </label>
              )}
            </div>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--text-muted)]">Reason</span>
              <input className="field" value={d.reason} maxLength={500} onChange={(e) => set({ reason: e.target.value })} />
            </label>

            {taken && (
              <div className="flex flex-wrap items-center gap-3 rounded-[5px] bg-[var(--warn-soft)] px-3 py-2 text-[var(--warn)]">
                <span>
                  {taken.category} belongs to team {taken.team}.
                </span>
                <button className="btn btn-secondary" onClick={() => void save(true)}>
                  Move it here
                </button>
              </div>
            )}
            {error && <p className="rounded-[5px] bg-[var(--danger-soft)] px-3 py-2 text-[var(--danger)]">{error}</p>}

            {detail && (
              <div className="flex flex-col gap-2 border-t border-[var(--border)] pt-3">
                <p className="text-xs text-[var(--text-muted)]">Members (Keycloak-managed members change through their groups)</p>
                <ul className="flex flex-col gap-1">
                  {detail.members.map((m) => (
                    <li key={m.username} className="flex items-center justify-between gap-3">
                      <span>
                        {m.username} · {m.role}
                        {!m.is_available && " · unavailable"} · <span className="text-[var(--text-muted)]">{m.source}</span>
                      </span>
                      {m.source === "local" && (
                        <button className="text-xs text-[var(--danger)] hover:underline" onClick={() => void removeMember(m.username)}>
                          Remove
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
                <div className="flex flex-wrap items-end gap-2">
                  <input
                    className="field"
                    placeholder="username (local account)"
                    value={newMember.username}
                    onChange={(e) => setNewMember({ ...newMember, username: e.target.value })}
                  />
                  <select className="field" value={newMember.role} onChange={(e) => setNewMember({ ...newMember, role: e.target.value })}>
                    <option value="member">member</option>
                    <option value="lead">lead</option>
                  </select>
                  <button className="btn btn-secondary" onClick={() => void addMember()}>
                    Add member
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
