"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useRequireAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import { priorityClasses } from "@/lib/badges";
import { QUEUE_LABEL } from "@/lib/explain";
import { dateTime, humanize, relativeTime } from "@/lib/format";
import type { Status, Workflow, WorkflowDetail } from "@/lib/lifecycle";
import type { StaffTicketRow } from "@/lib/types/generated";

type Card = StaffTicketRow;

interface MoveOption {
  status: { id: string };
  transition_name: string | null;
  rule_count: number;
}

interface Drag {
  card: Card;
  from: string;
  allowed: Map<string, MoveOption> | null;
}

export default function BoardPage() {
  const user = useRequireAuth();
  const router = useRouter();
  const search = useSearchParams();
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [wf, setWf] = useState<WorkflowDetail | null>(null);
  const [cards, setCards] = useState<Card[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [hideTriage, setHideTriage] = useState(true);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "danger" | "ok"; text: string; ticket?: string } | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);

  const workflowId = search.get("workflow") ?? workflows.find((w) => w.is_default)?.id ?? null;

  useEffect(() => {
    if (!user) return;
    api
      .get<Workflow[]>("/api/lifecycle/workflows")
      .then((all) => {
        setWorkflows(all);
        if (!all.some((w) => w.is_default)) setUnavailable("There is no default workflow yet. Create one in Settings → Workflows.");
      })
      .catch((err) =>
        setUnavailable(err instanceof ApiError && err.status === 403 ? "The board isn't available to your role." : "Couldn't load workflows."),
      );
  }, [user]);

  const latest = useRef(0);

  const load = useCallback(async () => {
    if (!workflowId) return;
    const request = ++latest.current;
    const params = new URLSearchParams({ workflow: workflowId });
    if (submitted) params.set("q", submitted);
    try {
      const [w, b] = await Promise.all([
        api.get<WorkflowDetail>(`/api/lifecycle/workflows/${workflowId}`),
        api.get<{ items: Card[]; counts: Record<string, number> }>(`/api/tickets/board?${params}`),
      ]);
      if (request !== latest.current) return;
      setWf(w);
      setCards(b.items);
      setCounts(b.counts);
      setUnavailable(null);
    } catch (err) {
      if (request !== latest.current) return;
      setUnavailable(err instanceof ApiError && err.status === 403 ? "The board isn't available to your role." : "Couldn't load the board.");
    }
  }, [workflowId, submitted]);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  const columns = useMemo(() => {
    if (!wf) return [];
    return [...wf.statuses].sort((a, b) => a.order - b.order).filter((s) => !hideTriage || !s.is_pipeline || counts[s.key]);
  }, [wf, hideTriage, counts]);

  if (!user) return null;

  const byKey = new Map<string, Card[]>();
  for (const c of cards ?? []) byKey.set(c.status.key, [...(byKey.get(c.status.key) ?? []), c]);

  const startDrag = (card: Card, status: Status) => {
    setNotice(null);
    setDrag({ card, from: status.id, allowed: null });
    api
      .get<MoveOption[]>(`/api/lifecycle/tickets/${card.public_id}/transitions`)
      .then((opts) => setDrag((d) => d && d.card.public_id === card.public_id ? { ...d, allowed: new Map(opts.map((o) => [o.status.id, o])) } : d))
      .catch(() => setDrag((d) => d && { ...d, allowed: new Map() }));
  };

  const drop = async (target: Status) => {
    const d = drag;
    setDrag(null);
    setOver(null);
    if (!d || target.id === d.from || !d.allowed?.has(target.id)) return;
    const previous = cards;
    setCards((cs) => cs && cs.map((c) => (c.public_id === d.card.public_id ? { ...c, status: { ...c.status, key: target.key, name: target.name, color: target.color } } : c)));
    try {
      const res = await api.post<{ waiting_transform: boolean }>(`/api/lifecycle/tickets/${d.card.public_id}/move`, {
        status_id: target.id,
        expected_version: d.card.version,
      });
      setNotice(
        res.waiting_transform
          ? { tone: "ok", text: `${d.card.public_id} is waiting on an action (an approval or a webhook) before it reaches ${target.name}.`, ticket: d.card.public_id }
          : null,
      );
      await load();
    } catch (err) {
      setCards(previous);
      setNotice({ tone: "danger", text: err instanceof ApiError ? err.message : "The move didn't go through.", ticket: d.card.public_id });
    }
  };

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] flex-col">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Board</h1>
          <p className="mt-0.5 text-sm text-[var(--text-muted)]">
            Drag a ticket to another column to move it. Columns it can't move to fade while you drag.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="field w-56"
            value={workflowId ?? ""}
            onChange={(e) => router.replace(`/board?workflow=${e.target.value}`)}
            aria-label="Workflow"
          >
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setSubmitted(query.trim());
            }}
          >
            <input className="field w-56" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter by ID or subject" aria-label="Filter tickets" />
          </form>
          <label className="flex items-center gap-1.5 text-sm text-[var(--text-muted)]">
            <input type="checkbox" checked={hideTriage} onChange={(e) => setHideTriage(e.target.checked)} />
            Hide empty triage columns
          </label>
          {wf && user.role === "manager" && (
            <Link href={`/settings/workflows/${wf.id}`} className="btn btn-secondary">
              Edit workflow
            </Link>
          )}
        </div>
      </header>

      {notice && (
        <p className={`tone-${notice.tone} mb-3 flex items-center justify-between gap-3 rounded-[5px] px-3 py-2 text-sm`}>
          <span>{notice.text}</span>
          <span className="flex shrink-0 gap-3">
            {notice.ticket && (
              <Link href={`/tickets/${notice.ticket}`} className="underline">
                Open ticket
              </Link>
            )}
            <button onClick={() => setNotice(null)} aria-label="Dismiss">
              ×
            </button>
          </span>
        </p>
      )}

      {unavailable ? (
        <p className="text-sm text-[var(--text-muted)]">{unavailable}</p>
      ) : !cards || !wf ? (
        <p className="text-sm text-[var(--text-muted)]">Loading…</p>
      ) : (
        <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto pb-2">
          {columns.map((status) => {
            const items = byKey.get(status.key) ?? [];
            const total = counts[status.key] ?? 0;
            const isSource = drag?.from === status.id;
            const option = drag?.allowed?.get(status.id);
            const allowed = !!option;
            const pending = drag && drag.allowed === null;
            const faded = drag && !isSource && !allowed && !pending;
            return (
              <section
                key={status.id}
                onDragOver={(e) => {
                  if (allowed) {
                    e.preventDefault();
                    setOver(status.id);
                  }
                }}
                onDragLeave={() => setOver((o) => (o === status.id ? null : o))}
                onDrop={(e) => {
                  e.preventDefault();
                  void drop(status);
                }}
                className={`flex w-[272px] shrink-0 flex-col rounded-[6px] border transition-opacity ${
                  over === status.id ? "border-[var(--text)] bg-[var(--surface-2)]" : "border-[var(--border)] bg-[var(--surface-2)]/60"
                } ${faded ? "opacity-40" : ""}`}
              >
                <div className="flex items-center gap-2 px-3 pb-2 pt-3">
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: status.color || "var(--border-strong)" }} />
                  <h2 className="truncate text-sm font-semibold">{status.name}</h2>
                  <span className="text-xs text-[var(--text-muted)]">{total}</span>
                  <span className="ml-auto truncate text-[11px] text-[var(--text-muted)]">{status.is_pipeline ? "Triage" : status.base.name}</span>
                </div>
                {drag && allowed && option && (
                  <p className="mx-3 mb-2 truncate text-[11px] text-[var(--text-muted)]">
                    {option.transition_name ?? "Allowed"}
                    {option.rule_count > 0 && ` · ${option.rule_count} check${option.rule_count === 1 ? "" : "s"}`}
                  </p>
                )}
                <ul className="flex min-h-16 flex-1 flex-col gap-2 overflow-y-auto px-2 pb-2">
                  {items.map((c) => (
                    <li
                      key={c.public_id}
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.effectAllowed = "move";
                        e.dataTransfer.setData("text/plain", c.public_id);
                        startDrag(c, status);
                      }}
                      onDragEnd={() => {
                        setDrag(null);
                        setOver(null);
                      }}
                      className={`cursor-grab rounded-[5px] border border-[var(--border)] bg-[var(--surface)] p-2.5 text-sm shadow-[0_1px_0_var(--border)] active:cursor-grabbing ${
                        drag?.card.public_id === c.public_id ? "opacity-50" : ""
                      }`}
                    >
                      <Link href={`/tickets/${c.public_id}`} className="line-clamp-2 font-medium hover:text-[var(--accent)]" draggable={false}>
                        {c.subject_masked}
                      </Link>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-[var(--text-muted)]">
                        <span className="font-mono">{c.public_id}</span>
                        {c.review && (
                          <span className={`badge ${priorityClasses(c.review.priority)}`} title={QUEUE_LABEL[c.review.queue] ?? humanize(c.review.queue)}>
                            P{c.review.priority}
                          </span>
                        )}
                        {c.category && <span>· {c.category}</span>}
                      </div>
                      <div className="mt-1.5 flex items-center justify-between gap-2 text-xs">
                        <span className="truncate text-[var(--text-muted)]">{c.assignee ?? c.assigned_team ?? "Unassigned"}</span>
                        <Sla due={c.sla_due_at} done={c.status.is_completed} />
                      </div>
                    </li>
                  ))}
                  {total > items.length && (
                    <li className="px-1 py-1 text-xs text-[var(--text-muted)]">
                      Showing the newest {items.length} of {total}.{" "}
                      <Link href={`/tickets?view=all`} className="underline">
                        See all tickets
                      </Link>
                    </li>
                  )}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Sla({ due, done }: { due: string | null; done: boolean }) {
  if (!due || done) return null;
  const overdue = new Date(due).getTime() < Date.now();
  return (
    <span className={`shrink-0 ${overdue ? "font-medium text-[var(--danger)]" : "text-[var(--text-muted)]"}`} title={dateTime(due)}>
      {overdue ? `Overdue ${relativeTime(due).replace(" ago", "")}` : `Due ${relativeTime(due)}`}
    </span>
  );
}
