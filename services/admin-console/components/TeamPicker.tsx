"use client";

// The team a team page shows: the teams the user belongs to, or every team for a manager.

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SessionUser } from "@/lib/session";
import type { TeamOut } from "@/lib/types/generated";

export function useVisibleTeams(user: SessionUser | null): TeamOut[] {
  const [teams, setTeams] = useState<TeamOut[]>([]);
  useEffect(() => {
    if (!user) return;
    api
      .get<TeamOut[]>("/api/teams")
      .then((all) => {
        const mine = new Set((user.teams ?? []).map((t) => t.team));
        setTeams(user.role === "manager" ? all : all.filter((t) => mine.has(t.slug)));
      })
      .catch(() => setTeams([]));
  }, [user]);
  return teams;
}

export default function TeamPicker({
  teams,
  value,
  onChange,
}: {
  teams: TeamOut[];
  value: string;
  onChange: (slug: string) => void;
}) {
  return (
    <label className="flex w-[200px] flex-col gap-1">
      <span className="text-[11px] text-[var(--text-muted)]">Team</span>
      <select className="field" value={value} onChange={(e) => onChange(e.target.value)}>
        {!teams.some((t) => t.slug === value) && <option value={value}>{value}</option>}
        {teams.map((t) => (
          <option key={t.slug} value={t.slug}>
            {t.name}
          </option>
        ))}
      </select>
    </label>
  );
}
