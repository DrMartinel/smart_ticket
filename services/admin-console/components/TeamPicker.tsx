"use client";

// The team a team page shows: the teams the user belongs to, or every team for a manager.

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SessionUser } from "@/lib/session";
import type { TeamOut } from "@/lib/types/generated";
import { NativeSelect } from "@/components/ui/native-select";
import { P, canEverywhere } from "@/lib/permissions";

export function useVisibleTeams(user: SessionUser | null): TeamOut[] {
  return useVisibleTeamsState(user).teams;
}

/** The visible teams and whether they have loaded. */
export function useVisibleTeamsState(user: SessionUser | null): { teams: TeamOut[]; loaded: boolean } {
  const [state, setState] = useState<{ teams: TeamOut[]; loaded: boolean }>({ teams: [], loaded: false });
  useEffect(() => {
    if (!user) return;
    api
      .get<TeamOut[]>("/api/teams")
      .then((all) => {
        const mine = new Set((user.teams ?? []).map((t) => t.team));
        setState({ teams: canEverywhere(user, P.reportsTeams) ? all : all.filter((t) => mine.has(t.slug)), loaded: true });
      })
      .catch(() => setState({ teams: [], loaded: true }));
  }, [user]);
  return state;
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
    <label className="flex w-full flex-col gap-1.5 sm:w-[200px]">
      <span className="text-xs font-medium text-foreground/80">Team</span>
      <NativeSelect value={value} onChange={(e) => onChange(e.target.value)}>
        {!teams.some((t) => t.slug === value) && <option value={value}>{value}</option>}
        {teams.map((t) => (
          <option key={t.slug} value={t.slug}>
            {t.name}
          </option>
        ))}
      </NativeSelect>
    </label>
  );
}
