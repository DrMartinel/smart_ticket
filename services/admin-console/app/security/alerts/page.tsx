"use client";

// The security inbox (F8 · Security inbox 15-1087): most severe first, then oldest.

import Link from "next/link";
import { useEffect, useState } from "react";
import { SeverityChip, StateChip, vnTime } from "@/components/security/badges";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { AlertRowOut } from "@/lib/types/generated";

const KINDS = [
  "pii_critical",
  "credential_in_reply",
  "refresh_token_reused",
  "break_glass_sign_in",
  "break_glass_in_keycloak",
  "injection_detected",
  "ambiguous_role",
  "reveal_rate_limited",
  "decrypt_failed",
  "reveal_failed",
  "access_denied_burst",
  "thresholds_unapproved",
];

export default function SecurityInboxPage() {
  const user = useRequireAuth();
  const [state, setState] = useState("open");
  const [kind, setKind] = useState("");
  const [assignee, setAssignee] = useState("");
  const [rows, setRows] = useState<AlertRowOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    const params = new URLSearchParams();
    if (state) params.set("state", state);
    if (kind) params.set("kind", kind);
    if (assignee.trim()) params.set("assignee", assignee.trim());
    api
      .get<AlertRowOut[]>(`/api/security/alerts?${params}`)
      .then((r) => {
        setRows(r);
        setError(null);
      })
      .catch(() => setError("Couldn't load the alerts."));
  }, [user, state, kind, assignee]);

  if (!user) return null;

  return (
    <div className="mx-auto flex max-w-[1180px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Security alerts</h1>
          <p className="text-xs text-[var(--text-muted)]">
            Severity first, then oldest. Ack targets: critical 1 business hour, high 4, medium 1 business day (BR-F8-04).
          </p>
        </div>
        <div className="flex flex-wrap gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">State</span>
            <select className="field" value={state} onChange={(e) => setState(e.target.value)}>
              <option value="open">open</option>
              <option value="new">new</option>
              <option value="acknowledged">acknowledged</option>
              <option value="investigating">investigating</option>
              <option value="closed">closed</option>
              <option value="">all</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">Kind</span>
            <select className="field" value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">all</option>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">Assignee</span>
            <input className="field w-32" value={assignee} placeholder="any" onChange={(e) => setAssignee(e.target.value)} />
          </label>
        </div>
      </header>

      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2.5 font-medium">Severity</th>
              <th className="px-4 py-2.5 font-medium">Kind</th>
              <th className="px-4 py-2.5 font-medium">Ticket / user</th>
              <th className="px-4 py-2.5 font-medium">Count</th>
              <th className="px-4 py-2.5 font-medium">First seen</th>
              <th className="px-4 py-2.5 font-medium">Ack due</th>
              <th className="px-4 py-2.5 font-medium">State</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows?.map((a) => (
              <tr
                key={a.id}
                className={`border-t border-[var(--border)] ${a.overdue || (a.severity === "critical" && a.state === "new") ? "bg-[var(--danger-soft)]" : ""}`}
              >
                <td className="px-4 py-2.5">
                  <SeverityChip severity={a.severity} />
                </td>
                <td className="px-4 py-2.5 font-mono text-xs">{a.kind}</td>
                <td className="px-4 py-2.5">
                  {a.ticket ? `${a.ticket.public_id} · ${a.ticket.reporter}` : a.subject_user ? `user ${a.subject_user}` : "—"}
                </td>
                <td className="px-4 py-2.5">{a.count}</td>
                <td className="px-4 py-2.5">{vnTime(a.first_seen_at)}</td>
                <td className="px-4 py-2.5">
                  {a.acknowledged_at ? (
                    <span className="badge bg-[var(--ok-soft)] text-[var(--ok)]">acked {vnTime(a.acknowledged_at)}</span>
                  ) : a.overdue ? (
                    <span className="badge bg-[var(--danger-soft)] text-[var(--danger)]">overdue {vnTime(a.ack_due_at)}</span>
                  ) : (
                    <span className="badge bg-[var(--accent-soft)] text-[var(--accent)]">{vnTime(a.ack_due_at)}</span>
                  )}
                </td>
                <td className="px-4 py-2.5">
                  <StateChip state={a.state} resolution={a.resolution} />
                </td>
                <td className="px-4 py-2.5 text-right">
                  <Link href={`/security/alerts/${a.id}`} className="text-[var(--accent)] hover:underline">
                    Open
                  </Link>
                </td>
              </tr>
            ))}
            {rows?.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-6 text-center text-[var(--text-muted)]">
                  No alerts.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-[var(--text-muted)]">
        Same kind + same ticket (or user) within 60 min increments one alert (BR-F8-03). Managers see only counts by kind and
        state (BR-F8-01).
      </p>
    </div>
  );
}
