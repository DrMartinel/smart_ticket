"use client";

// Opens the first team the user can see.

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useVisibleTeams } from "@/components/TeamPicker";
import { useRequireAuth } from "@/lib/auth";

export default function TeamsIndexPage() {
  const user = useRequireAuth();
  const router = useRouter();
  const teams = useVisibleTeams(user);

  useEffect(() => {
    if (teams.length > 0) router.replace(`/teams/${teams[0].slug}`);
  }, [teams, router]);

  if (!user) return null;
  return <p className="text-sm text-[var(--text-muted)]">{teams.length === 0 ? "You're not in a team yet." : "Opening…"}</p>;
}
