"use client";

// Security alert counts for managers (F8 BR-F8-01, FR-F8-009): kinds and states, no tickets or people.

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { SummaryOut } from "@/lib/types/generated";

const STATES = ["new", "acknowledged", "investigating", "closed"];

export default function SecuritySummaryPage() {
  const user = useRequireAuth();
  const [summary, setSummary] = useState<SummaryOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user) api.get<SummaryOut>("/api/security/summary").then(setSummary).catch(() => setError("Couldn't load the summary."));
  }, [user]);

  if (!user) return null;
  const kinds = [...new Set(summary?.cells.map((c) => c.kind) ?? [])].sort();
  const count = (kind: string, state: string) => summary?.cells.find((c) => c.kind === kind && c.state === state)?.count ?? 0;

  return (
    <div className="mx-auto flex max-w-[900px] flex-col gap-4">
      <header>
        <h1 className="text-xl font-semibold">Security alerts · last {summary?.days ?? 30} days</h1>
        <p className="text-xs text-[var(--text-muted)]">Counts only: the alerts themselves are for security (BR-F8-01).</p>
      </header>
      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
      <div className="card overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2.5 font-medium">Kind</th>
              {STATES.map((s) => (
                <th key={s} className="px-4 py-2.5 text-right font-medium">
                  {s}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {kinds.map((k) => (
              <tr key={k} className="border-t border-[var(--border)]">
                <td className="px-4 py-2.5 font-mono text-xs">{k}</td>
                {STATES.map((s) => (
                  <td key={s} className="px-4 py-2.5 text-right">
                    {count(k, s)}
                  </td>
                ))}
              </tr>
            ))}
            {summary && kinds.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-[var(--text-muted)]">
                  No alerts in the window.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
