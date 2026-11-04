"use client";

// One alert (F8 · Alert detail 15-1265): the ticket or user behind it, its timeline, and what
// security can do: acknowledge, assign, note, tell the requester, release, end sessions, close.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { SeverityChip, StateChip, vnTime } from "@/components/security/badges";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { piiLevelTone } from "@/lib/badges";
import type { AlertDetailOut, CloseIn } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

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
  if (!alert) return <p className="text-sm text-muted-foreground">{error ?? "Loading…"}</p>;

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
      <Link href="/security/alerts" className="text-sm text-muted-foreground hover:text-foreground">
        ← Alerts
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <span className="font-mono">{alert.kind}</span>
            {alert.ticket && <span>· {alert.ticket.public_id}</span>}
          </h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <SeverityChip severity={alert.severity} />
            <StateChip state={alert.state} resolution={alert.resolution} />
            Raised {vnTime(alert.first_seen_at)} (+07) · count {alert.count}
            {alert.subject_user && ` · subject user ${alert.subject_user}`} · ack due {vnTime(alert.ack_due_at)}
            {alert.assignee && ` · assigned to ${alert.assignee}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {alert.state === "new" && (
            <Button variant="outline" disabled={busy} onClick={() => act(() => api.post(`${base}/ack`))}>
              Acknowledge
            </Button>
          )}
          {alert.can_notify_requester && (
            <Button variant="outline"
              disabled={busy}
              onClick={() => act(() => api.post(`${base}/notify-requester`))}
            >
              {alert.requester_notified_at ? "Notify requester again" : "Notify requester"}
            </Button>
          )}
          {alert.sessions.length > 0 && (
            <Button variant="outline" disabled={busy} onClick={() => act(() => api.post(`${base}/end-sessions`))}>
              End {alert.sessions.length} sign-in{alert.sessions.length > 1 ? "s" : ""}
            </Button>
          )}
        </div>
      </header>

      {error && <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card asChild>
          <section className="flex flex-col gap-4 p-5">
            {alert.ticket ? (
              <div>
                <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Ticket (masked)</p>
                <Link href={`/tickets/${alert.ticket.public_id}`} className="mt-1 block font-medium hover:underline">
                  {alert.ticket.subject_masked}
                </Link>
                <p className="mt-1 whitespace-pre-wrap break-words text-sm">{alert.ticket.body_masked}</p>
                <p className="mt-2 flex flex-wrap gap-2 text-xs">
                  <Badge variant={piiLevelTone(alert.ticket.pii_level)}>PII: {alert.ticket.pii_level}</Badge>
                  <Badge variant="neutral">{alert.ticket.status}</Badge>
                  <Badge variant="neutral">from {alert.ticket.reporter}</Badge>
                </p>
              </div>
            ) : (
              <p className="text-sm">{alert.detail}</p>
            )}

            {(alert.sessions.length > 0 || alert.recent_activity.length > 0) && (
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wider text-muted-foreground">Live sign-ins</p>
                  {alert.sessions.length === 0 ? (
                    <p className="text-xs text-muted-foreground">None.</p>
                  ) : (
                    <ul className="text-xs">
                      {alert.sessions.slice(0, 5).map((s) => (
                        <li key={s.created_at} className="border-t border-border py-1.5">
                          {s.client} · IP {s.ip_address ?? "?"} · since {vnTime(s.created_at)}
                        </li>
                      ))}
                      {alert.sessions.length > 5 && (
                        <li className="border-t border-border py-1.5 text-muted-foreground">
                          and {alert.sessions.length - 5} more
                        </li>
                      )}
                    </ul>
                  )}
                </div>
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wider text-muted-foreground">Recent activity</p>
                  <ul className="text-xs">
                    {alert.recent_activity.map((a) => (
                      <li key={`${a.event}-${a.occurred_at}`} className="border-t border-border py-1.5">
                        {vnTime(a.occurred_at)} · <span className="font-mono">{a.event}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wider text-muted-foreground">Timeline</p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="py-1.5">Time</TableHead>
                    <TableHead className="py-1.5">Event</TableHead>
                    <TableHead className="py-1.5">Actor</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {alert.events.map((e, i) => (
                    <TableRow key={i} className="align-top">
                      <TableCell className="py-2 pr-3 text-xs">{vnTime(e.at)}</TableCell>
                      <TableCell className="py-2 pr-3">
                        {e.kind}
                        {e.note_masked && <span className="block text-xs text-muted-foreground">“{e.note_masked}”</span>}
                      </TableCell>
                      <TableCell className="py-2 text-xs">{e.actor ?? "system"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void act(() => api.post(`${base}/notes`, { note })).then(() => setNote(""));
              }}
            >
              <Input className="flex-1" value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} placeholder="Add a note (masked)" />
              <Button variant="outline" disabled={busy || !note.trim()}>
                Add note
              </Button>
            </form>
          </section>
        </Card>

        <aside className="flex flex-col gap-4">
          {alert.state !== "closed" ? (
            <Card asChild>
              <section className="flex flex-col gap-3 p-5 text-sm">
                <h2 className="font-medium">{alert.can_release ? "Release or close" : "Close"}</h2>
                {alert.can_release && (
                  <p className="text-xs text-muted-foreground">
                    Release rejects the security review item with your reason (an eval candidate), moves the ticket to
                    pending review and opens a low-confidence item for a person. It never runs through the AI again
                    (BR-F8-06).
                  </p>
                )}
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">{alert.can_release ? "Reason (masked)" : "Closing note (masked)"}</span>
                  <Textarea className="min-h-[64px]" value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} />
                </label>
                <fieldset className="flex flex-col gap-1">
                  <legend className="pb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">Close alert as</legend>
                  <RadioGroup value={resolution} onValueChange={(next) => setResolution(next as typeof resolution)} className="gap-1.5">
                    {(["false_positive", "true_positive", "duplicate"] as const).map((r) => (
                      <label key={r} className="flex items-center gap-2">
                        <RadioGroupItem value={r} />
                        {r}
                      </label>
                    ))}
                  </RadioGroup>
                  {resolution === "duplicate" && (
                    <Input className="mt-1" value={duplicateOf} onChange={(e) => setDuplicateOf(e.target.value)} placeholder="Alert id it duplicates" />
                  )}
                </fieldset>
                <div className="flex flex-wrap gap-2">
                  {alert.can_release && (
                    <Button
                      disabled={busy || !reason.trim()}
                      onClick={() =>
                        act(async () => {
                          await api.post(`${base}/release-ticket`, { reason });
                          await api.post(`${base}/close`, closeBody(reason));
                        })
                      }
                    >
                      Release and close
                    </Button>
                  )}
                  <Button
                    variant={alert.can_release ? "outline" : "default"}
                    disabled={busy || !reason.trim()}
                    onClick={() => act(() => api.post(`${base}/close`, closeBody(reason)))}
                  >
                    {alert.can_release ? "Close, keep blocked" : "Close"}
                  </Button>
                </div>
                <div className="flex gap-2 border-t border-border pt-3">
                  <Input className="flex-1" value={assignee} onChange={(e) => setAssignee(e.target.value)} placeholder="security username" />
                  <Button variant="outline"
                    disabled={busy || !assignee.trim()}
                    onClick={() => act(() => api.post(`${base}/assign`, { user: assignee.trim() }))}
                  >
                    Assign
                  </Button>
                </div>
              </section>
            </Card>
          ) : (
            <Card asChild>
              <section className="flex flex-col gap-3 p-5 text-sm">
                <h2 className="font-medium">Closed as {alert.resolution}</h2>
                <Textarea className="min-h-[64px]" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why reopen? (masked)" />
                <Button variant="outline"
                  className="self-start"
                  disabled={busy || !reason.trim()}
                  onClick={() => act(() => api.post(`${base}/reopen`, { note: reason }))}
                >
                  Reopen
                </Button>
              </section>
            </Card>
          )}
        </aside>
      </div>
    </div>
  );
}
