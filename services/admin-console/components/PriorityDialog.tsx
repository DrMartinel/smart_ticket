"use client";

// Change a ticket's priority with a reason (F1 · Priority dialog 8-677).

import { useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { ApiError, api } from "@/lib/api";
import type { PolicyOut, Priority, PriorityIn, SlaBadgeOut, TicketSlaOut } from "@/lib/types/generated";

const PRIORITIES: Priority[] = ["P1", "P2", "P3", "P4"];

/** The first active policy by order for a category and priority (BR-F1-03). */
function matching(policies: PolicyOut[], category: string | null, priority: string): PolicyOut | undefined {
  return policies
    .filter((p) => p.state === "active")
    .filter((p) => !p.category || p.category === category)
    .filter((p) => !p.priority || p.priority === priority)
    .sort((a, b) => a.order - b.order)[0];
}

export default function PriorityDialog({
  open,
  onClose,
  onDone,
  ticket,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
  ticket: { public_id: string; subject: string; category: string | null; priority: string | null; version: number; sla: SlaBadgeOut | null | undefined };
}) {
  const [priority, setPriority] = useState<Priority>((ticket.priority as Priority) ?? "P3");
  const [reason, setReason] = useState("");
  const [policies, setPolicies] = useState<PolicyOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setPriority((ticket.priority as Priority) ?? "P3");
    setReason("");
    setError(null);
    api.get<PolicyOut[]>("/api/sla/policies").then(setPolicies).catch(() => setPolicies([]));
  }, [open, ticket.priority]);

  const target = matching(policies, ticket.category, priority);
  const changes = (ticket.sla?.clocks ?? []).map((c) => {
    const name = c.kind === "response" ? "Response" : "Resolution";
    if (c.state === "met" || c.state === "cancelled") return `${name} clock: already ${c.state}, unchanged.`;
    const next = target ? (c.kind === "response" ? target.response_minutes : target.resolution_minutes) : c.target_minutes;
    const breach = c.elapsed_minutes >= next ? " It is breached at once." : "";
    return `${name} clock: target ${c.target_minutes.toLocaleString()} → ${next.toLocaleString()} business min; ${c.elapsed_minutes.toLocaleString()} min already used are kept.${breach}`;
  });

  const submit = async () => {
    setBusy(true);
    setError(null);
    const body: PriorityIn = { priority, reason, expected_version: ticket.version };
    try {
      await api.patch<TicketSlaOut>(`/api/tickets/${encodeURIComponent(ticket.public_id)}/priority`, body);
      onDone();
    } catch (err) {
      if (err instanceof ApiError && err.code === "version_conflict") setError("The ticket changed meanwhile. Close this and try again.");
      else if (err instanceof ApiError && err.code === "not_allowed") setError("Only the assignee, the team lead or a manager can change the priority.");
      else setError(err instanceof ApiError ? err.message : "Couldn't change the priority.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Change priority"
      subtitle={`${ticket.public_id} · ${ticket.subject}`}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy || !reason.trim() || priority === ticket.priority} onClick={() => void submit()}>
            Change priority
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-4 text-sm">
        <fieldset className="flex flex-wrap gap-4">
          <legend className="pb-1.5 text-[11px] font-medium uppercase tracking-wider text-[var(--text-muted)]">New priority</legend>
          {PRIORITIES.map((p) => (
            <label key={p} className="flex items-center gap-1.5">
              <input type="radio" name="priority" checked={priority === p} onChange={() => setPriority(p)} />
              {p}
              {p === ticket.priority && <span className="text-[var(--text-muted)]">(current)</span>}
            </label>
          ))}
        </fieldset>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--text-muted)]">Reason (required)</span>
          <input className="field" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
        </label>
        {priority !== ticket.priority && changes.length > 0 && (
          <div className="rounded-[5px] border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2.5">
            <p className="pb-1 font-medium">What changes{target ? ` (policy ${target.name})` : ""}</p>
            {changes.map((line) => (
              <p key={line} className="text-xs">
                {line}
              </p>
            ))}
          </div>
        )}
        {error && <p className="rounded-[5px] bg-[var(--danger-soft)] px-3 py-2 text-[var(--danger)]">{error}</p>}
      </div>
    </Modal>
  );
}
