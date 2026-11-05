"use client";

// One incident (F7 · Incident page 14-1090): confirm or dismiss a proposal, broadcast updates with
// an ETA, resolve with close-all (Resolve dialog 14-1324), unlink a wrongly matched ticket.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { IncidentStatusChip, STAGES, StageChip, eta, fromLocal } from "@/components/incidents/chips";
import { vnTime } from "@/components/security/badges";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { BroadcastOut, CloseResultOut, IncidentDetailOut } from "@/lib/types/generated";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Labeled } from "@/components/Modal";
import { Page, PageHeader } from "@/components/ui/page-header";
import { Decision, Panel, Proposal } from "@/components/ui/panel";
import { EmptyState, ErrorState, LoadingState, TableStatus } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { Link2, Megaphone } from "lucide-react";
import { P, can } from "@/lib/permissions";

const CATEGORIES = ["network", "access", "hardware", "software", "security", "other"];

function Stat({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: string }) {
  return (
    <Card className="px-4 py-3">
      <p className="eyebrow">{label}</p>
      <p className="num mt-1.5 text-lg font-medium">{value}</p>
      {note && <p className={`mt-0.5 text-xs ${tone ?? "text-muted-foreground"}`}>{note}</p>}
    </Card>
  );
}

function remaining(target: string): string {
  const minutes = Math.round((new Date(target).getTime() - Date.now()) / 60000);
  if (minutes < 0) return "Overdue";
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m left`;
}

export default function IncidentPage() {
  const user = useRequireAuth();
  const { id } = useParams<{ id: string }>();
  const [incident, setIncident] = useState<IncidentDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<"confirm" | "dismiss" | "resolve" | "reopen" | null>(null);
  const [unlinking, setUnlinking] = useState<string | null>(null);
  const [result, setResult] = useState<CloseResultOut | null>(null);

  // Confirm
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("network");
  const [service, setService] = useState("");
  // Dismiss, reopen, unlink, resolve
  const [reason, setReason] = useState("");
  const [closeAll, setCloseAll] = useState(true);
  // Broadcast
  const [stage, setStage] = useState("investigating");
  const [bodyVi, setBodyVi] = useState("");
  const [bodyEn, setBodyEn] = useState("");
  const [etaAt, setEtaAt] = useState("");
  const [etaUnknown, setEtaUnknown] = useState(false);

  const toast = useToast();
  const isManager = can(user, P.incidentsManage);

  const load = useCallback(() => {
    api
      .get<IncidentDetailOut>(`/api/incidents/${id}`)
      .then((i) => {
        setIncident(i);
        setTitle((t) => t || i.title.replace(/^Proposed: /, ""));
        setStage((s) => (i.stage && i.stage !== "resolved" ? i.stage : s));
        setError(null);
      })
      .catch((e) => setError(e instanceof ApiError && e.status === 404 ? "This incident doesn't exist." : "Couldn't load this incident."));
  }, [id]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  async function act(run: () => Promise<unknown>) {
    setBusy(true);
    try {
      await run();
      setDialog(null);
      setUnlinking(null);
      setReason("");
      toast.success("Saved.");
      load();
    } catch (e) {
      setError(e instanceof ApiError ? `${e.message}${e.code ? ` (${e.code})` : ""}` : "That didn't go through. Try again.");
    } finally {
      setBusy(false);
    }
  }

  if (!user) return null;
  if (!incident)
    return (
      <Page width="record">
        <PageHeader eyebrow="Workspace / Incident" title={error ? "Incident" : "Loading incident…"} back={{ href: "/incidents", label: "Incidents" }} />
        {error ? <ErrorState title={error} onRetry={load} /> : <LoadingState rows={5} label="Loading incident" />}
      </Page>
    );

  const latest: BroadcastOut | undefined = incident.broadcasts[0];
  const det = incident.detector as Record<string, number>;
  const canBroadcast = isManager && (incident.status === "confirmed" || incident.status === "resolved");

  return (
    <Page width="record" className="flex flex-col gap-5">
      <PageHeader
        className="mb-1"
        eyebrow="Workspace / Incident"
        vi="Sự cố diện rộng"
        back={{ href: "/incidents", label: "Incidents" }}
        title={incident.title}
        meta={
          <>
            <span className="num rounded-sm bg-muted px-1.5 py-0.5 text-xs text-foreground">{incident.public_id}</span>
            <IncidentStatusChip status={incident.status} />
            {incident.category ?? "no category yet"}
            {incident.service && ` · service ${incident.service}`}
            {incident.confirmed_at && ` · confirmed ${vnTime(incident.confirmed_at)} by ${incident.confirmed_by}`}
            {incident.status !== "proposed" && (
              <>
                {" · stage "}
                <StageChip stage={incident.stage} />
              </>
            )}
          </>
        }
        actions={
          isManager && (
          <div className="flex flex-wrap gap-2">
            {incident.status === "proposed" && (
              <>
                <Button variant="outline" onClick={() => setDialog("dismiss")}>
                  Not an incident…
                </Button>
                <Button onClick={() => setDialog("confirm")}>
                  Confirm incident…
                </Button>
              </>
            )}
            {incident.status === "confirmed" && (
              <Button onClick={() => setDialog("resolve")}>
                Mark resolved…
              </Button>
            )}
            {incident.status === "resolved" && (
              <Button variant="outline" onClick={() => setDialog("reopen")}>
                Reopen…
              </Button>
            )}
          </div>
          )
        }
      />

      {error && <ErrorState title="That didn't go through">{error}</ErrorState>}
      {incident.status === "proposed" && (
        <Proposal label="Detector proposal">
          The detector saw an unusual number of similar tickets. Nothing has changed for them yet: an incident manager confirms this as an
          incident or dismisses it.
        </Proposal>
      )}
      {result && (
        <Alert variant={result.failed.length > 0 ? "warn" : "ok"}>
          <AlertDescription>
          Closed {result.closed.length} ticket{result.closed.length === 1 ? "" : "s"}.
          {result.failed.length > 0 && (
            <>
              {" "}
              <span className="font-medium">{result.failed.length} couldn&apos;t be closed:</span>{" "}
              {result.failed.map((f) => `${f.ticket} (${f.code})`).join(", ")}. Their assignees have been told.
            </>
          )}
          </AlertDescription>
        </Alert>
      )}
      {incident.dismiss_reason && (
        <Decision label="Dismissed">{incident.dismiss_reason}</Decision>
      )}
      {incident.resolution_note_masked && (
        <Decision label="Resolution note">{incident.resolution_note_masked}</Decision>
      )}

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Linked tickets" value={String(incident.ticket_count)} note={`from ${incident.requesters} requester${incident.requesters === 1 ? "" : "s"}`} />
        <Stat
          label="Detection"
          value={det.count !== undefined ? `${det.count} in ${det.window_minutes ?? "?"} min` : incident.detected_by}
          note={det.count !== undefined ? `baseline ${Number(det.baseline).toFixed(2)} · σ ${Number(det.sigma).toFixed(2)} · min_count ${det.min_count ?? "?"}` : "declared by hand"}
        />
        <Stat
          label="Incident SLA"
          value={incident.target_resolve_at ? remaining(incident.target_resolve_at) : "—"}
          note={incident.target_resolve_at ? `due ${vnTime(incident.target_resolve_at)} (ICT), 24×7` : "starts when confirmed"}
          tone={incident.target_breached ? "text-danger" : "text-warn"}
        />
        <Stat
          label="Last broadcast"
          value={latest ? vnTime(latest.sent_at) : "—"}
          note={
            latest
              ? `${latest.delivery.in_app_delivered} in-app · ${latest.delivery.email_delivered} email · ${latest.delivery.email_failed} email failed`
              : "none yet"
          }
        />
      </section>

      {canBroadcast && (
        <Panel title="Broadcast an update">
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-[1fr_1fr_auto] sm:items-end">
              <Labeled label="Stage">
                <NativeSelect value={stage} onChange={(e) => setStage(e.target.value)}>
                  {STAGES.filter((s) => s !== "resolved").map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </NativeSelect>
              </Labeled>
              <Labeled label="Expected fix (ICT, +07)">
                <Input
                  type="datetime-local"
                  value={etaAt}
                  disabled={etaUnknown}
                  onChange={(e) => setEtaAt(e.target.value)}
                />
              </Labeled>
              <label className="flex min-h-9 items-center gap-2 text-sm">
                <Checkbox checked={etaUnknown} onCheckedChange={(checked) => setEtaUnknown(checked === true)} />
                Not known yet
              </label>
            </div>
            <Labeled label="Message (Vietnamese)" required>
              <Textarea lang="vi" className="min-h-16" value={bodyVi} onChange={(e) => setBodyVi(e.target.value)} />
            </Labeled>
            <Labeled label="Message (English, optional)">
              <Textarea className="min-h-12" value={bodyEn} onChange={(e) => setBodyEn(e.target.value)} />
            </Labeled>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs text-muted-foreground">
                Sent once to each of the {incident.requesters} requesters, in the app and by email, and added as a public comment on every linked ticket.
              </p>
              <Button
                disabled={busy || !bodyVi.trim()}
                onClick={() =>
                  act(async () => {
                    await api.post(`/api/incidents/${incident.public_id}/broadcasts`, {
                      stage,
                      body_vi: bodyVi,
                      body_en: bodyEn,
                      eta: etaUnknown ? null : fromLocal(etaAt),
                      eta_unknown: etaUnknown,
                    });
                    setBodyVi("");
                    setBodyEn("");
                  })
                }
              >
                {busy ? "Sending…" : "Send update"}
              </Button>
            </div>
          </div>
        </Panel>
      )}

      <Panel title="Broadcast history" flush>
          <Table className="min-w-[760px]">
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Stage</TableHead>
                <TableHead>Message</TableHead>
                <TableHead>ETA</TableHead>
                <TableHead>Delivered</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {incident.broadcasts.map((b) => (
                <TableRow key={b.id}>
                  <TableCell className="num text-xs whitespace-nowrap">{vnTime(b.sent_at)}</TableCell>
                  <TableCell>
                    <StageChip stage={b.stage} />
                  </TableCell>
                  <TableCell>
                    {b.body_vi_masked}
                    {b.body_en_masked && <div className="text-xs text-muted-foreground">{b.body_en_masked}</div>}
                  </TableCell>
                  <TableCell>{eta(b.eta, b.eta_unknown)}</TableCell>
                  <TableCell>
                    {b.delivery.in_app_delivered} / {b.delivery.email_delivered} email
                    {b.delivery.email_failed > 0 && <span className="text-danger"> · {b.delivery.email_failed} failed</span>}
                  </TableCell>
                </TableRow>
              ))}
              <TableStatus
                colSpan={5}
                rows={incident.broadcasts}
                empty={
                  <EmptyState compact icon={Megaphone} title="No updates sent yet">
                    {canBroadcast ? "Send the first update above so affected people know you're on it." : "Updates appear here once an incident manager sends one."}
                  </EmptyState>
                }
              />
            </TableBody>
          </Table>
      </Panel>

      <Panel title={`Linked tickets · ${incident.links.length}`} flush>
          <Table className="min-w-[760px]">
            <TableHeader>
              <TableRow>
                <TableHead>Ticket</TableHead>
                <TableHead>Subject (masked)</TableHead>
                <TableHead>Requester</TableHead>
                <TableHead>Linked</TableHead>
                <TableHead>Clock</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {incident.links.map((l) => (
                <TableRow key={l.ticket}>
                  <TableCell>
                    <Link href={`/tickets/${l.ticket}`} className="num text-primary hover:underline">
                      {l.ticket}
                    </Link>
                  </TableCell>
                  <TableCell>{l.subject_masked}</TableCell>
                  <TableCell>{l.requester}</TableCell>
                  <TableCell>
                    {vnTime(l.linked_at)}
                    <span className="text-xs text-muted-foreground">
                      {" "}
                      · {l.linked_by}
                      {l.similarity !== null && ` ${l.similarity.toFixed(2)}`}
                    </span>
                  </TableCell>
                  <TableCell>
                    {l.clock_state === "paused" ? (
                      <Badge variant="neutral">Paused</Badge>
                    ) : (
                      <Badge variant="neutral">{l.clock_state ?? "—"}</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {(can(user, P.incidentsUnlink) || l.assigned_to === user.username) && incident.status !== "closed" && (
                      <Button variant="link" size="inline"  onClick={() => setUnlinking(l.ticket)}>
                        Unlink…
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              <TableStatus
                colSpan={6}
                rows={incident.links}
                empty={<EmptyState compact icon={Link2} title="No tickets linked">Similar new tickets attach here automatically.</EmptyState>}
              />
            </TableBody>
          </Table>
      </Panel>

      <Modal
        open={dialog === "confirm"}
        title="Confirm the incident"
        subtitle="Every linked ticket waiting for review is approved under your name, and their resolution clocks pause."
        onClose={() => setDialog(null)}
        footer={
          <>
          <Button variant="outline" onClick={() => setDialog(null)}>Cancel</Button>
          <Button
            disabled={busy || title.trim().length < 3}
            onClick={() => act(() => api.post(`/api/incidents/${incident.public_id}/confirm`, { title, category, service }))}
          >
            Confirm incident
          </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4 text-sm">
          <Labeled label="Incident name" required hint="At least 3 characters.">
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Labeled>
          <Labeled label="Category">
            <NativeSelect value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </NativeSelect>
          </Labeled>
          <Labeled label="Affected service">
            <Input value={service} onChange={(e) => setService(e.target.value)} />
          </Labeled>
        </div>
      </Modal>

      <Modal
        open={dialog === "dismiss" || dialog === "reopen" || unlinking !== null}
        title={dialog === "dismiss" ? "Dismiss: not an incident" : dialog === "reopen" ? "Reopen the incident" : `Unlink ${unlinking}`}
        subtitle={
          dialog === "dismiss"
            ? "The tickets are unlinked and stay in review as usual."
            : dialog === "reopen"
              ? "The clocks of the tickets still open pause again."
              : "The ticket goes back to the low-confidence review queue and its clock runs again."
        }
        onClose={() => {
          setDialog(null);
          setUnlinking(null);
        }}
        footer={
          <>
          <Button variant="outline" onClick={() => { setDialog(null); setUnlinking(null); }}>Cancel</Button>
          <Button
            variant={dialog === "reopen" ? "default" : "destructive"}
            disabled={busy || !reason.trim()}
            onClick={() =>
              act(() =>
                unlinking
                  ? api.delete(`/api/incidents/${incident.public_id}/links/${unlinking}`, { reason })
                  : api.post(`/api/incidents/${incident.public_id}/${dialog}`, { reason }),
              )
            }
          >
            {dialog === "dismiss" ? "Dismiss" : dialog === "reopen" ? "Reopen" : "Unlink ticket"}
          </Button>
          </>
        }
      >
        <Labeled label="Reason" required hint="Recorded in the incident's history.">
          <Textarea className="min-h-16" value={reason} onChange={(e) => setReason(e.target.value)} />
        </Labeled>
      </Modal>

      <Modal
        open={dialog === "resolve"}
        title="Mark the incident resolved"
        subtitle="Sends a final update (stage: resolved) to every requester."
        onClose={() => setDialog(null)}
        footer={
          <>
          <Button variant="outline" onClick={() => setDialog(null)}>Cancel</Button>
          <Button
            disabled={busy || !reason.trim()}
            onClick={() =>
              act(async () => {
                setResult(
                  await api.post<CloseResultOut>(`/api/incidents/${incident.public_id}/resolve`, {
                    resolution_note: reason,
                    close_all: closeAll,
                  }),
                );
              })
            }
          >
            Mark resolved
          </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4 text-sm">
          <Labeled label="Resolution note (public)" required hint="Requesters see this.">
            <Textarea className="min-h-20" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Labeled>
          <label className="flex min-h-9 items-center gap-2">
            <Checkbox checked={closeAll} onCheckedChange={(checked) => setCloseAll(checked === true)} />
            Close all {incident.links.length} linked tickets
          </label>
          <p className="text-xs text-muted-foreground">
            {closeAll
              ? "Each ticket moves to resolved through its own workflow; any that refuse are listed and their assignees are told."
              : "The tickets stay open and their resolution clocks run again."}
          </p>
        </div>
      </Modal>
    </Page>
  );
}
