"use client";

import ReassignDialog from "@/components/ReassignDialog";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useRequireAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import { BRANCH_LABEL, INTENT_LABEL, QUEUE_LABEL, reasonText } from "@/lib/explain";
import { dateTime, humanize, percent, relativeTime } from "@/lib/format";
import { piiLevelClasses, priorityClasses } from "@/lib/badges";
import PiiText from "@/components/PiiText";
import StatusChip from "@/components/StatusChip";
import ReviewForm, { type ReviewDecisionPayload } from "@/components/ReviewForm";
import TrustSignalsPanel, { type TrustSignalsPanelProps } from "@/components/TrustSignalsPanel";
import type { StaffTicketDetail } from "@/lib/types/generated";

type Detail = StaffTicketDetail;

interface Lifecycle {
  status: string;
  workflow_status: { id: string; key: string; name: string; is_pipeline: boolean } | null;
  version: number;
  waiting_transform: boolean;
  field_values: { field_id: string; field_name: string; value: unknown }[];
}

interface Move {
  status: { id: string; key: string; name: string; color: string };
  transition_id: string | null;
  transition_name: string | null;
  rule_count: number;
}

interface Transfer {
  id: string;
  trigger: string;
  state: string;
  failure_reason: string;
  before_status_name: string | null;
  after_status_name: string | null;
  actor_username: string | null;
  created_at: string;
}

interface ReviewItemDetail {
  claimed_by: string | null;
  trust_signals: TrustSignalsPanelProps["trustSignals"];
  trust_score: number | null;
  trust_contributions: Record<string, number> | null;
  routing_decisions: TrustSignalsPanelProps["routingDecision"][];
}

const TRIAGE = new Set(["new", "awaiting_requester"]);

export default function TicketPage() {
  const user = useRequireAuth();
  const { id } = useParams<{ id: string }>();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [lifecycle, setLifecycle] = useState<Lifecycle | null>(null);
  const [moves, setMoves] = useState<Move[]>([]);
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [lifecycleRefused, setLifecycleRefused] = useState(false);
  const [reviewItem, setReviewItem] = useState<ReviewItemDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await api.get<Detail>(`/api/tickets/${id}/detail`);
      setDetail(d);
      setReviewItem(d.review ? await api.get<ReviewItemDetail>(`/api/review/items/${d.review.id}`) : null);
    } catch {
      setError("Couldn't load this ticket.");
      return;
    }
    try {
      const [l, m, t] = await Promise.all([
        api.get<Lifecycle>(`/api/lifecycle/tickets/${id}`),
        api.get<Move[]>(`/api/lifecycle/tickets/${id}/transitions`),
        api.get<Transfer[]>(`/api/lifecycle/tickets/${id}/transfers`),
      ]);
      setLifecycle(l);
      setMoves(m);
      setTransfers(t);
      setLifecycleRefused(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setLifecycleRefused(true);
      else setError("Couldn't load this ticket.");
    }
  }, [id]);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;
  if (error) return <p className="text-sm text-[var(--danger)]">{error}</p>;
  if (!detail || (!lifecycle && !lifecycleRefused)) return <p className="text-sm text-[var(--text-muted)]">Loading…</p>;

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setNotice(null);
    try {
      await fn();
      setNotice(done);
      await load();
    } catch (err) {
      setNotice(err instanceof ApiError ? `Not done: ${err.message}` : "Not done: something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const latest = detail.routing[0];
  const mayReveal = user.role === "technician" || user.role === "security";

  return (
    <div className="mx-auto max-w-[1280px]">
      <Link href="/tickets?view=all" className="text-sm text-[var(--text-muted)] hover:text-[var(--text)]">
        ← Tickets
      </Link>
      <header className="mb-6 mt-2">
        <h1 className="text-2xl font-semibold tracking-tight">{detail.subject_masked}</h1>
        <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-[var(--text-muted)]">
          <span className="font-mono text-[var(--text)]">{detail.public_id}</span>
          <StatusChip name={detail.status.name} color={detail.status.color} />
          <span>
            from {detail.reporter_person.username} via {humanize(detail.source).toLowerCase()}
          </span>
          <span title={dateTime(detail.created_at)}>{relativeTime(detail.created_at)}</span>
        </p>
      </header>

      {notice && (
        <p className={`mb-4 rounded-[5px] px-3 py-2 text-sm ${notice.startsWith("Not done") ? "tone-danger" : "tone-ok"}`}>
          {notice}
        </p>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col gap-6">
          <Section title="Request">
            <div className="whitespace-pre-wrap text-[15px] leading-7">
              <PiiText
                publicId={detail.public_id}
                text={detail.body_masked}
                placeholders={detail.pii_placeholders ?? []}
                canReveal={mayReveal}
                isSecurity={user.role === "security"}
              />
            </div>
            {mayReveal && (detail.pii_placeholders ?? []).length > 0 && (
              <p className="mt-2 text-[11px] text-[var(--text-muted)]">
                Chips are placeholders. Click one to reveal it; you need the claim on this ticket&apos;s review item or its
                assignment, and every reveal is logged.
              </p>
            )}
            {detail.clarifications.map((c) => (
              <div key={c.asked_at} className="mt-4 border-t border-[var(--border)] pt-3 text-sm">
                <p className="text-[var(--text-muted)]">Asked the requester · {relativeTime(c.asked_at)}</p>
                <p className="mt-1">{c.question}</p>
                {c.options.length > 0 && <p className="mt-1 text-[var(--text-muted)]">Options: {c.options.join(" · ")}</p>}
                <p className="mt-1">
                  {c.answer_masked ? (
                    <>
                      <span className="text-[var(--text-muted)]">Answer:</span> {c.answer_masked}
                    </>
                  ) : (
                    <span className="text-[var(--text-muted)]">No answer.</span>
                  )}
                </p>
              </div>
            ))}
          </Section>

          <Section title="What the AI concluded">
            {!latest && !detail.ai ? (
              <p className="text-sm text-[var(--text-muted)]">The triage pipeline hasn&apos;t finished with this ticket yet.</p>
            ) : (
              <div className="flex flex-col gap-4 text-sm">
                {latest && (
                  <div>
                    <p className="text-[15px] font-medium">
                      {BRANCH_LABEL[latest.branch] ?? humanize(latest.branch)}
                      {latest.shadow_mode && latest.branch !== "hitl" && (
                        <span className="ml-2 align-middle text-xs font-normal text-[var(--text-muted)]">
                          (shadow mode: proposed only, a person handles it)
                        </span>
                      )}
                    </p>
                    <p className="mt-1 text-[var(--text-muted)]">{reasonText(latest.reason_code)}</p>
                  </div>
                )}
                {detail.ai && (
                  <dl className="grid grid-cols-[140px_minmax(0,1fr)] gap-x-4 gap-y-2">
                    <dt className="text-[var(--text-muted)]">Proposed</dt>
                    <dd>{detail.ai.proposed_intent ? INTENT_LABEL[detail.ai.proposed_intent] ?? humanize(detail.ai.proposed_intent) : "Nothing"}</dd>
                    <dt className="text-[var(--text-muted)]">Category</dt>
                    <dd>
                      {detail.ai.category ?? "Not chosen"}
                      {detail.ai.category && detail.ai.category_confidence !== null && (
                        <span className="text-[var(--text-muted)]"> · {percent(detail.ai.category_confidence, 0)} sure</span>
                      )}
                    </dd>
                    {detail.ai.kb_title && (
                      <>
                        <dt className="text-[var(--text-muted)]">Help page</dt>
                        <dd>{detail.ai.kb_title}</dd>
                      </>
                    )}
                    {detail.ai.trust_score !== null && (
                      <>
                        <dt className="text-[var(--text-muted)]">Trust score</dt>
                        <dd className="font-mono">{detail.ai.trust_score.toFixed(2)}</dd>
                      </>
                    )}
                    {detail.ai.degraded_reason && (
                      <>
                        <dt className="text-[var(--text-muted)]">Problem</dt>
                        <dd>{reasonText(detail.ai.degraded_reason)}</dd>
                      </>
                    )}
                  </dl>
                )}
                {detail.ai?.answer_draft && (
                  <div className="rounded-[5px] bg-[var(--surface-2)] p-3">
                    <p className="mb-1 text-xs font-medium text-[var(--text-muted)]">Drafted answer</p>
                    <p className="whitespace-pre-wrap">{detail.ai.answer_draft}</p>
                    {detail.ai.verbatim_quote && (
                      <blockquote className="mt-2 border-l-2 border-[var(--border-strong)] pl-3 text-[var(--text-muted)]">
                        {detail.ai.verbatim_quote}
                      </blockquote>
                    )}
                  </div>
                )}
                {reviewItem && (
                  <details className="group">
                    <summary className="cursor-pointer text-sm text-[var(--accent)]">Show the scoring details</summary>
                    <div className="mt-3">
                      <TrustSignalsPanel
                        trustSignals={reviewItem.trust_signals}
                        trustScore={reviewItem.trust_score}
                        trustContributions={reviewItem.trust_contributions}
                        routingDecision={reviewItem.routing_decisions[0] ?? null}
                      />
                    </div>
                  </details>
                )}
              </div>
            )}
          </Section>

          {detail.review && (
            <Section
              title="Review"
              aside={
                <span className="flex items-center gap-2 text-sm">
                  <span className={`badge ${priorityClasses(detail.review.priority)}`}>P{detail.review.priority}</span>
                  {QUEUE_LABEL[detail.review.queue] ?? humanize(detail.review.queue)}
                </span>
              }
            >
              {detail.review.state === "pending" ? (
                <div className="flex items-center justify-between gap-4 rounded-[5px] bg-[var(--surface-2)] px-3 py-2.5 text-sm">
                  <span>Nobody is working on this review yet.</span>
                  <button
                    className="btn btn-secondary"
                    disabled={busy}
                    onClick={() =>
                      act(() => api.post(`/api/review/items/${detail.review!.id}/claim`), "You've claimed this review.")
                    }
                  >
                    Claim it
                  </button>
                </div>
              ) : (
                <ReviewForm
                  hasAutoReplyProposal={detail.ai?.proposed_intent === "auto_reply"}
                  aiCategory={detail.ai?.category ?? null}
                  submitting={busy}
                  onSubmit={(payload: ReviewDecisionPayload) =>
                    act(() => api.post(`/api/review/items/${detail.review!.id}/decide`, payload), "Review saved.")
                  }
                />
              )}
            </Section>
          )}

          <Section title="History">
            <Timeline detail={detail} transfers={transfers} />
          </Section>
        </div>

        <aside className="flex flex-col gap-6">
          <Section title="Status">
            <StatusChip name={detail.status.name} color={detail.status.color} />
            {detail.status.stage && <p className="mt-1 text-xs text-[var(--text-muted)]">Stage: {detail.status.stage}</p>}
            {lifecycle?.waiting_transform && (
              <p className="tone-warn mt-3 rounded-[5px] px-2.5 py-1.5 text-xs">A move is in progress: its actions are running.</p>
            )}
            <div className="mt-4">
              {!lifecycle ? (
                <p className="text-xs text-[var(--text-muted)]">Moves and the ticket&apos;s history aren&apos;t available to your role.</p>
              ) : TRIAGE.has(detail.status.key) ? (
                <p className="text-xs text-[var(--text-muted)]">
                  Triage or the requester has this ticket. It can be moved once triage has finished.
                </p>
              ) : moves.length === 0 ? (
                <p className="text-xs text-[var(--text-muted)]">No moves from here.</p>
              ) : (
                <>
                  <p className="mb-2 text-xs font-medium text-[var(--text-muted)]">Move to</p>
                  <div className="flex flex-col gap-1.5">
                    {moves.map((m) => (
                      <button
                        key={m.status.id}
                        disabled={busy || lifecycle.waiting_transform}
                        onClick={() =>
                          act(
                            () =>
                              api.post(`/api/lifecycle/tickets/${id}/move`, {
                                status_id: m.status.id,
                                expected_version: lifecycle.version,
                              }),
                            `Moved to ${m.status.name}.`,
                          )
                        }
                        className="btn btn-secondary justify-between text-left"
                        title={m.transition_name ?? undefined}
                      >
                        <StatusChip name={m.status.name} color={m.status.color} />
                        {m.rule_count > 0 && (
                          <span className="text-xs text-[var(--text-muted)]">
                            {m.rule_count} check{m.rule_count > 1 ? "s" : ""}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          </Section>

          {lifecycle && (
            <OwnerCard
              ticket={{
                public_id: detail.public_id,
                subject: detail.subject_masked,
                team: detail.assigned_team,
                assignee: detail.assignee,
                category: detail.category,
                version: detail.version,
              }}
              canTake={!detail.assignee && !!detail.assigned_team && (user.role === "manager" || (user.teams ?? []).some((t) => t.team === detail.assigned_team))}
              busy={busy}
              onTake={() =>
                act(
                  () => api.post(`/api/tickets/${id}/take`, { expected_version: detail.version }),
                  "You have the ticket.",
                )
              }
              onReassigned={() => void load()}
            />
          )}

          <Section title="Details">
            <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
              <dt className="text-[var(--text-muted)]">Category</dt>
              <dd>{detail.category ?? "—"}</dd>
              <dt className="text-[var(--text-muted)]">Requester</dt>
              <dd className="truncate">{detail.reporter_person.email || detail.reporter_person.username}</dd>
              <dt className="text-[var(--text-muted)]">Personal data</dt>
              <dd>
                <span className={`badge ${piiLevelClasses(detail.pii_level)}`}>PII: {humanize(detail.pii_level).toLowerCase()}</span>
              </dd>
              <dt className="text-[var(--text-muted)]">SLA due</dt>
              <dd>{dateTime(detail.sla_due_at)}</dd>
              <dt className="text-[var(--text-muted)]">Resolved</dt>
              <dd>{dateTime(detail.resolved_at)}</dd>
              <dt className="text-[var(--text-muted)]">Reopened</dt>
              <dd>{detail.reopened_count}×</dd>
            </dl>
          </Section>

          {lifecycle && lifecycle.field_values.length > 0 && (
            <Section title="Fields">
              <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
                {lifecycle.field_values.map((f) => (
                  <div key={f.field_id} className="contents">
                    <dt className="text-[var(--text-muted)]">{f.field_name}</dt>
                    <dd className="break-words">{f.value === null ? "—" : String(f.value)}</dd>
                  </div>
                ))}
              </dl>
            </Section>
          )}
        </aside>
      </div>
    </div>
  );
}

function Section({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="card p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function OwnerCard({
  ticket,
  canTake,
  busy,
  onTake,
  onReassigned,
}: {
  ticket: { public_id: string; subject: string; team: string | null; assignee: string | null; category: string | null; version: number };
  canTake: boolean;
  busy: boolean;
  onTake: () => void;
  onReassigned: () => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <Section
      title="Owner"
      aside={
        <button className="text-xs text-[var(--accent)]" onClick={() => setOpen(true)}>
          Reassign…
        </button>
      }
    >
      <div className="flex items-center justify-between gap-3 text-sm">
        <div>
          <p>{ticket.assignee ?? <span className="text-[var(--text-muted)]">Unassigned</span>}</p>
          <p className="text-[var(--text-muted)]">{ticket.team ? `Team ${ticket.team}` : "No team"}</p>
        </div>
        {canTake && (
          <button className="btn btn-primary" disabled={busy} onClick={onTake}>
            Take
          </button>
        )}
      </div>
      <ReassignDialog
        open={open}
        onClose={() => setOpen(false)}
        onDone={() => {
          setOpen(false);
          onReassigned();
        }}
        ticket={ticket}
      />
    </Section>
  );
}

type Event = { at: string; title: string; detail?: string; tone?: "danger" };

function Timeline({ detail, transfers }: { detail: Detail; transfers: Transfer[] }) {
  const events: Event[] = [
    { at: detail.created_at, title: `Submitted by ${detail.reporter_person.username}` },
    ...detail.routing.map((r) => ({
      at: r.decided_at,
      title: `Triage: ${(BRANCH_LABEL[r.branch] ?? humanize(r.branch)).toLowerCase()}`,
      detail: reasonText(r.reason_code),
    })),
    ...transfers
      .filter((t) => t.before_status_name !== t.after_status_name)
      .map((t) => ({
        at: t.created_at,
        title: `${t.before_status_name ? `${t.before_status_name} → ` : ""}${t.after_status_name ?? "?"}`,
        detail:
          t.state === "failed"
            ? `Failed: ${t.failure_reason}`
            : t.state === "cancelled"
              ? `Cancelled: ${t.failure_reason}`
              : t.actor_username
                ? `by ${t.actor_username}`
                : t.trigger === "action"
                  ? "by an automation"
                  : "by the system",
        tone: t.state === "failed" ? ("danger" as const) : undefined,
      })),
  ].sort((a, b) => b.at.localeCompare(a.at));

  return (
    <ol className="relative ml-1.5 border-l border-[var(--border)]">
      {events.map((e, i) => (
        <li key={`${e.at}-${i}`} className="relative pb-4 pl-5 last:pb-0">
          <span className="absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-[var(--surface)] bg-[var(--border-strong)]" />
          <p className="text-sm">
            <span className="font-medium">{e.title}</span>
            <span className="ml-2 text-xs text-[var(--text-muted)]" title={dateTime(e.at)}>
              {relativeTime(e.at)}
            </span>
          </p>
          {e.detail && (
            <p className={`text-sm ${e.tone === "danger" ? "text-[var(--danger)]" : "text-[var(--text-muted)]"}`}>{e.detail}</p>
          )}
        </li>
      ))}
    </ol>
  );
}
