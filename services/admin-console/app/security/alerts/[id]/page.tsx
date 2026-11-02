"use client";

// One alert (F8 · Alert detail 15-1265): the ticket or user behind it, its timeline, and what
// security can do: acknowledge, assign, note, tell the requester, release, end sessions, close.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { SeverityChip, StateChip, vnTime } from "@/components/security/badges";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { piiLevelClasses } from "@/lib/badges";
import type { AlertDetailOut, CloseIn } from "@/lib/types/generated";

type Resolution = CloseIn["resolution"];

export default function AlertPage() {
  const user = useRequireAuth();
  const { id } = useParams<{ id: string }>();
  const [alert, setAlert] = useState<AlertDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [resolution, setResolution] = useState<Resolution>("false_positive");
  const [duplicateOf, setDuplicateOf] = useState("");
  const [assignee, setAssignee] = useState("");

  const load = useCallback(async () => {
    try {
      setAlert(await api.get<AlertDetailOut>(`/api/security/alerts/${id}`));
    } catch {
      setError("Couldn't load the alert.");
    }
  }, [id]);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;
  if (!alert) return <p className="text-sm text-[var(--text-muted)]">{error ?? "Loading…"}</p>;

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setReason("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? `${err.code ?? "refused"}: ${err.message}` : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const base = `/api/security/alerts/${alert.id}`;
  const closeBody = (text: string): CloseIn => ({
    resolution,
    note: text,
    duplicate_of: resolution === "duplicate" ? duplicateOf || null : null,
  });

  return (
    <div className="mx-auto flex max-w-[1180px] flex-col gap-4">
      <Link href="/security/alerts" className="text-sm text-[var(--text-muted)] hover:text-[var(--text)]">
        ← Alerts
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <span className="font-mono">{alert.kind}</span>
            {alert.ticket && <span>· {alert.ticket.public_id}</span>}
          </h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--text-muted)]">
            <SeverityChip severity={alert.severity} />
            <StateChip state={alert.state} resolution={alert.resolution} />
            Raised {vnTime(alert.first_seen_at)} (+07) · count {alert.count}
            {alert.subject_user && ` · subject user ${alert.subject_user}`} · ack due {vnTime(alert.ack_due_at)}
            {alert.assignee && ` · assigned to ${alert.assignee}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {alert.state === "new" && (
            <button className="btn btn-secondary" disabled={busy} onClick={() => act(() => api.post(`${base}/ack`))}>
              Acknowledge
            </button>
          )}
          {alert.can_notify_requester && (
            <button
              className="btn btn-secondary"
              disabled={busy}
              onClick={() => act(() => api.post(`${base}/notify-requester`))}
            >
              {alert.requester_notified_at ? "Notify requester again" : "Notify requester"}
            </button>
          )}
          {alert.sessions.length > 0 && (
            <button className="btn btn-secondary" disabled={busy} onClick={() => act(() => api.post(`${base}/end-sessions`))}>
              End {alert.sessions.length} sign-in{alert.sessions.length > 1 ? "s" : ""}
            </button>
          )}
        </div>
      </header>

      {error && <p className="rounded-[5px] bg-[var(--danger-soft)] px-3 py-2 text-sm text-[var(--danger)]">{error}</p>}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section className="card flex flex-col gap-4 p-5">
          {alert.ticket ? (
            <div>
              <p className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">Ticket (masked)</p>
              <Link href={`/tickets/${alert.ticket.public_id}`} className="mt-1 block font-medium hover:underline">
                {alert.ticket.subject_masked}
              </Link>
              <p className="mt-1 whitespace-pre-wrap break-words text-sm">{alert.ticket.body_masked}</p>
              <p className="mt-2 flex flex-wrap gap-2 text-xs">
                <span className={`badge ${piiLevelClasses(alert.ticket.pii_level)}`}>PII: {alert.ticket.pii_level}</span>
                <span className="badge">{alert.ticket.status}</span>
                <span className="badge">from {alert.ticket.reporter}</span>
              </p>
            </div>
          ) : (
            <p className="text-sm">{alert.detail}</p>
          )}

          {(alert.sessions.length > 0 || alert.recent_activity.length > 0) && (
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <p className="mb-1 text-[11px] uppercase tracking-wider text-[var(--text-muted)]">Live sign-ins</p>
                {alert.sessions.length === 0 ? (
                  <p className="text-xs text-[var(--text-muted)]">None.</p>
                ) : (
                  <ul className="text-xs">
                    {alert.sessions.slice(0, 5).map((s) => (
                      <li key={s.created_at} className="border-t border-[var(--border)] py-1.5">
                        {s.client} · IP {s.ip_address ?? "?"} · since {vnTime(s.created_at)}
                      </li>
                    ))}
                    {alert.sessions.length > 5 && (
                      <li className="border-t border-[var(--border)] py-1.5 text-[var(--text-muted)]">
                        and {alert.sessions.length - 5} more
                      </li>
                    )}
                  </ul>
                )}
              </div>
              <div>
                <p className="mb-1 text-[11px] uppercase tracking-wider text-[var(--text-muted)]">Recent activity</p>
                <ul className="text-xs">
                  {alert.recent_activity.map((a) => (
                    <li key={`${a.event}-${a.occurred_at}`} className="border-t border-[var(--border)] py-1.5">
                      {vnTime(a.occurred_at)} · <span className="font-mono">{a.event}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          <div>
            <p className="mb-1 text-[11px] uppercase tracking-wider text-[var(--text-muted)]">Timeline</p>
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-[var(--text-muted)]">
                <tr>
                  <th className="py-1.5 font-normal">Time</th>
                  <th className="py-1.5 font-normal">Event</th>
                  <th className="py-1.5 font-normal">Actor</th>
                </tr>
              </thead>
              <tbody>
                {alert.events.map((e, i) => (
                  <tr key={i} className="border-t border-[var(--border)] align-top">
                    <td className="py-2 pr-3 text-xs">{vnTime(e.at)}</td>
                    <td className="py-2 pr-3">
                      {e.kind}
                      {e.note_masked && <span className="block text-xs text-[var(--text-muted)]">“{e.note_masked}”</span>}
                    </td>
                    <td className="py-2 text-xs">{e.actor ?? "system"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void act(() => api.post(`${base}/notes`, { note })).then(() => setNote(""));
            }}
          >
            <input className="field flex-1" value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} placeholder="Add a note (masked)" />
            <button className="btn btn-secondary" disabled={busy || !note.trim()}>
              Add note
            </button>
          </form>
        </section>

        <aside className="flex flex-col gap-4">
          {alert.state !== "closed" ? (
            <section className="card flex flex-col gap-3 p-5 text-sm">
              <h2 className="font-medium">{alert.can_release ? "Release or close" : "Close"}</h2>
              {alert.can_release && (
                <p className="text-xs text-[var(--text-muted)]">
                  Release rejects the security review item with your reason (an eval candidate), moves the ticket to
                  pending review and opens a low-confidence item for a person. It never runs through the AI again
                  (BR-F8-06).
                </p>
              )}
              <label className="flex flex-col gap-1">
                <span className="text-xs text-[var(--text-muted)]">{alert.can_release ? "Reason (masked)" : "Closing note (masked)"}</span>
                <textarea className="field min-h-[64px]" value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} />
              </label>
              <fieldset className="flex flex-col gap-1">
                <legend className="pb-1 text-[11px] uppercase tracking-wider text-[var(--text-muted)]">Close alert as</legend>
                {(["false_positive", "true_positive", "duplicate"] as const).map((r) => (
                  <label key={r} className="flex items-center gap-2">
                    <input type="radio" name="resolution" checked={resolution === r} onChange={() => setResolution(r)} />
                    {r}
                  </label>
                ))}
                {resolution === "duplicate" && (
                  <input className="field mt-1" value={duplicateOf} onChange={(e) => setDuplicateOf(e.target.value)} placeholder="Alert id it duplicates" />
                )}
              </fieldset>
              <div className="flex flex-wrap gap-2">
                {alert.can_release && (
                  <button
                    className="btn btn-primary"
                    disabled={busy || !reason.trim()}
                    onClick={() =>
                      act(async () => {
                        await api.post(`${base}/release-ticket`, { reason });
                        await api.post(`${base}/close`, closeBody(reason));
                      })
                    }
                  >
                    Release and close
                  </button>
                )}
                <button
                  className={alert.can_release ? "btn btn-secondary" : "btn btn-primary"}
                  disabled={busy || !reason.trim()}
                  onClick={() => act(() => api.post(`${base}/close`, closeBody(reason)))}
                >
                  {alert.can_release ? "Close, keep blocked" : "Close"}
                </button>
              </div>
              <div className="flex gap-2 border-t border-[var(--border)] pt-3">
                <input className="field flex-1" value={assignee} onChange={(e) => setAssignee(e.target.value)} placeholder="security username" />
                <button
                  className="btn btn-secondary"
                  disabled={busy || !assignee.trim()}
                  onClick={() => act(() => api.post(`${base}/assign`, { user: assignee.trim() }))}
                >
                  Assign
                </button>
              </div>
            </section>
          ) : (
            <section className="card flex flex-col gap-3 p-5 text-sm">
              <h2 className="font-medium">Closed as {alert.resolution}</h2>
              <textarea className="field min-h-[64px]" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why reopen? (masked)" />
              <button
                className="btn btn-secondary self-start"
                disabled={busy || !reason.trim()}
                onClick={() => act(() => api.post(`${base}/reopen`, { note: reason }))}
              >
                Reopen
              </button>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
