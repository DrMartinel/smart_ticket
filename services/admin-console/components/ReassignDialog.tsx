"use client";

// Reassign a ticket with a reason (F2 · Reassign dialog 9-442).

import { useEffect, useMemo, useState } from "react";
import Modal from "@/components/Modal";
import { ApiError, api } from "@/lib/api";
import type { AssignedTicketOut, ReassignIn, ReassignReason, TeamDetailOut, TeamOut, TicketCategory } from "@/lib/types/generated";

const REASONS: { code: ReassignReason; label: string }[] = [
  { code: "wrong_team", label: "Sai đội xử lý · Wrong team" },
  { code: "workload", label: "Cân bằng tải · Workload" },
  { code: "skill", label: "Cần chuyên môn khác · Skill" },
  { code: "leave", label: "Nghỉ phép · Leave" },
  { code: "escalation", label: "Chuyển cấp · Escalation" },
  { code: "requester_request", label: "Người yêu cầu đề nghị · Requester request" },
  { code: "other", label: "Khác · Other" },
];

const NOTE_MIN = 10;

function refusal(err: unknown): string {
  if (!(err instanceof ApiError)) return "Couldn't reassign.";
  switch (err.code) {
    case "lead_required":
      return "Only the team lead or a manager moves a ticket to another team.";
    case "reason_required":
      return `Write a note of at least ${NOTE_MIN} characters.`;
    case "version_conflict":
      return "The ticket changed meanwhile. Close this and try again.";
    case "user_not_in_team":
      return "That person isn't an active member of the team.";
    case "category_required":
      return "Pick which of the team's categories the ticket moves to.";
    default:
      return err.message;
  }
}

export default function ReassignDialog({
  open,
  onClose,
  onDone,
  ticket,
}: {
  open: boolean;
  onClose: () => void;
  onDone: (result: AssignedTicketOut) => void;
  ticket: {
    public_id: string;
    subject: string;
    team: string | null;
    assignee: string | null;
    category: string | null;
    version: number;
  };
}) {
  const [teams, setTeams] = useState<TeamOut[]>([]);
  const [toTeam, setToTeam] = useState(ticket.team ?? "");
  const [members, setMembers] = useState<string[]>([]);
  const [toUser, setToUser] = useState("");
  const [toCategory, setToCategory] = useState("");
  const [reason, setReason] = useState<ReassignReason>("workload");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setToTeam(ticket.team ?? "");
    setToUser("");
    setNote("");
    setError(null);
    api.get<TeamOut[]>("/api/teams").then(setTeams).catch(() => setError("Couldn't load the teams."));
  }, [open, ticket.team]);

  useEffect(() => {
    if (!open || !toTeam) return;
    setToUser("");
    api
      .get<TeamDetailOut>(`/api/teams/${encodeURIComponent(toTeam)}`)
      .then((t) => setMembers(t.members.map((m) => m.username)))
      .catch(() => setMembers([]));
  }, [open, toTeam]);

  const target = teams.find((t) => t.slug === toTeam);
  const moving = !!target && toTeam !== ticket.team;
  const categoryChoices = useMemo(() => {
    if (!target || !moving || (ticket.category && target.categories.includes(ticket.category))) return [];
    return target.categories;
  }, [target, moving, ticket.category]);
  const newCategory = categoryChoices.length === 1 ? categoryChoices[0] : toCategory;

  useEffect(() => setToCategory(""), [toTeam]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    const body: ReassignIn = {
      to_team: moving ? toTeam : null,
      to_user: toUser || null,
      to_category: categoryChoices.length > 1 && toCategory ? (toCategory as TicketCategory) : null,
      reason_code: reason,
      note,
      expected_version: ticket.version,
    };
    try {
      onDone(await api.post<AssignedTicketOut>(`/api/tickets/${encodeURIComponent(ticket.public_id)}/reassign`, body));
    } catch (err) {
      setError(refusal(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Reassign ${ticket.public_id}`}
      subtitle={`${ticket.subject} · now: ${ticket.team ?? "no team"} / ${ticket.assignee ?? "unassigned"}`}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy || note.trim().length < NOTE_MIN || (categoryChoices.length > 1 && !toCategory)} onClick={() => void submit()}>
            Reassign
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-4 text-sm">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">To team</span>
            <select className="field" value={toTeam} onChange={(e) => setToTeam(e.target.value)}>
              {!ticket.team && <option value="">Choose a team…</option>}
              {teams.map((t) => (
                <option key={t.slug} value={t.slug}>
                  {t.name} ({t.categories.join(", ")})
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">To person</span>
            <select className="field" value={toUser} onChange={(e) => setToUser(e.target.value)}>
              <option value="">Team strategy picks</option>
              {members.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
        </div>

        {categoryChoices.length > 1 && (
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">New category</span>
            <select className="field" value={toCategory} onChange={(e) => setToCategory(e.target.value)}>
              <option value="">Choose…</option>
              {categoryChoices.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        )}

        <fieldset className="flex flex-col gap-1.5">
          <legend className="pb-1 text-[11px] font-medium uppercase tracking-wider text-[var(--text-muted)]">Reason code</legend>
          {REASONS.map((r) => (
            <label key={r.code} className="flex items-center gap-2">
              <input type="radio" name="reason_code" checked={reason === r.code} onChange={() => setReason(r.code)} />
              <span>
                <span className="font-mono text-xs">{r.code}</span> — {r.label}
              </span>
            </label>
          ))}
        </fieldset>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--text-muted)]">Note (at least {NOTE_MIN} characters; personal data is masked before saving)</span>
          <textarea className="field min-h-[72px]" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
        </label>

        {moving && newCategory && newCategory !== ticket.category && (
          <p className="rounded-[5px] bg-[var(--warn-soft)] px-3 py-2 text-[var(--warn)]">
            Category changes {ticket.category ?? "none"} → {newCategory}. This is recorded as a reroute and becomes an
            evaluation case. The routing decision itself doesn&apos;t change.
          </p>
        )}
        {error && <p className="rounded-[5px] bg-[var(--danger-soft)] px-3 py-2 text-[var(--danger)]">{error}</p>}
      </div>
    </Modal>
  );
}
