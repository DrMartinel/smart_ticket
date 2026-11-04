"use client";

// Thresholds (F9): the thresholds.yaml core-api loaded, read-only; it changes by pull request
// (ADR-0044).

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { CurrentThresholdsOut } from "@/lib/types/generated";
import { Card } from "@/components/ui/card";
import { SectionTabs } from "@/components/TabNav";

export default function ThresholdsPage() {
  const user = useRequireAuth();
  const [current, setCurrent] = useState<CurrentThresholdsOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user)
      api
        .get<CurrentThresholdsOut>("/api/thresholds/current")
        .then(setCurrent)
        .catch(() => setError("Couldn't load the thresholds."));
  }, [user]);

  if (!user) return null;

  return (
    <div className="mx-auto flex max-w-[1080px] flex-col gap-4">
      <SectionTabs className="mb-1" />
      <header>
        <h1 className="text-xl font-semibold">Thresholds</h1>
        <p className="text-xs text-muted-foreground">
          thresholds.yaml is the only home of tunables. It changes by pull request, under a new version; every decision records the
          numbers it ran under (ADR-0044).
        </p>
      </header>
      {error && <p className="text-sm text-danger">{error}</p>}

      {current && (
        <Card asChild>
          <section className="flex flex-col gap-3 p-4 text-sm">
            <div>
              <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Loaded file</p>
              <p className="mt-1 font-mono text-lg font-semibold">{current.version}</p>
              <p className="text-xs text-muted-foreground">sha256 {current.sha256.slice(0, 12)}…</p>
            </div>
            <pre className="max-h-[640px] overflow-auto rounded-md bg-muted p-3 text-xs">{current.yaml}</pre>
          </section>
        </Card>
      )}
    </div>
  );
}
