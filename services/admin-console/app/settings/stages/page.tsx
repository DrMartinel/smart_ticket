"use client";

import { useEffect, useState } from "react";
import { useRequireAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import Modal, { Labeled } from "@/components/Modal";
import StatusChip from "@/components/StatusChip";
import { ColorPicker } from "@/components/workflow/Dialogs";
import { PALETTE, type Stage } from "@/lib/lifecycle";

type Kind = "backlog" | "active" | "completed";

const KIND_LABEL: Record<Kind, string> = {
  backlog: "Not started",
  active: "In progress",
  completed: "Resolved",
};

const kindOf = (s: Stage): Kind => (s.is_completed ? "completed" : s.is_backlog ? "backlog" : "active");

export default function StagesPage() {
  const user = useRequireAuth();
  const [stages, setStages] = useState<Stage[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Stage | "new" | null>(null);

  const load = () =>
    api
      .get<Stage[]>("/api/lifecycle/system-statuses")
      .then((s) => setStages([...s].sort((a, b) => a.order - b.order)))
      .catch(() => setError("Couldn't load stages."));

  useEffect(() => {
    if (user) void load();
  }, [user]);

  if (!user) return null;
  const canEdit = user.role === "manager";

  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't work.");
    }
  };

  const move = (i: number, d: number) => {
    if (!stages) return;
    const next = [...stages];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    setStages(next);
    void run(() => api.post("/api/lifecycle/system-statuses/reorder", { ids: next.map((s) => s.id) }));
  };

  return (
    <div className="mx-auto max-w-[880px]">
      <header className="mb-5 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Stages</h1>
          <p className="mt-0.5 max-w-2xl text-sm text-[var(--text-muted)]">
            The system stages every workflow status maps onto. Reports and SLAs read the stage, so workflows can name their statuses freely.
          </p>
        </div>
        {canEdit && (
          <button className="btn btn-primary" onClick={() => setEditing("new")}>
            New stage
          </button>
        )}
      </header>

      {error && <p className="tone-danger mb-4 rounded-[5px] px-3 py-2 text-sm">{error}</p>}

      {stages && (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[var(--surface-2)] text-left text-xs text-[var(--text-muted)]">
              <tr>
                <th className="w-12 px-4 py-2.5 font-medium">#</th>
                <th className="px-4 py-2.5 font-medium">Stage</th>
                <th className="px-4 py-2.5 font-medium">Counts as</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {stages.map((s, i) => (
                <tr key={s.id} className="border-t border-[var(--border)]">
                  <td className="px-4 py-3 text-[var(--text-muted)]">{i + 1}</td>
                  <td className="px-4 py-3">
                    <StatusChip name={s.name} color={s.color} />
                    {s.description && <p className="text-xs text-[var(--text-muted)]">{s.description}</p>}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`badge ${s.is_completed ? "tone-ok" : s.is_backlog ? "tone-neutral" : "tone-info"}`}>{KIND_LABEL[kindOf(s)]}</span>
                  </td>
                  <td className="px-4 py-3">
                    {canEdit && (
                      <span className="flex items-center justify-end gap-1 text-xs">
                        <button className="btn btn-secondary px-2 py-0.5" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Move ${s.name} up`}>
                          ↑
                        </button>
                        <button
                          className="btn btn-secondary px-2 py-0.5"
                          disabled={i === stages.length - 1}
                          onClick={() => move(i, 1)}
                          aria-label={`Move ${s.name} down`}
                        >
                          ↓
                        </button>
                        <button className="ml-2 hover:underline" onClick={() => setEditing(s)}>
                          Edit
                        </button>
                        <button
                          className="ml-2 text-[var(--danger)] hover:underline"
                          onClick={() => confirm(`Delete stage "${s.name}"?`) && run(() => api.delete(`/api/lifecycle/system-statuses/${s.id}`))}
                        >
                          Delete
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <StageDialog
        stage={editing === "new" ? null : editing}
        open={editing !== null}
        onClose={() => setEditing(null)}
        onSave={async (body) => {
          if (editing === "new") await api.post("/api/lifecycle/system-statuses", body);
          else if (editing) await api.patch(`/api/lifecycle/system-statuses/${editing.id}`, body);
          setEditing(null);
          await load();
        }}
      />
    </div>
  );
}

function StageDialog({
  stage,
  open,
  onClose,
  onSave,
}: {
  stage: Stage | null;
  open: boolean;
  onClose: () => void;
  onSave: (body: object) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState(PALETTE[0]);
  const [kind, setKind] = useState<Kind>("active");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setName(stage?.name ?? "");
    setDescription(stage?.description ?? "");
    setColor(stage?.color ?? PALETTE[0]);
    setKind(stage ? kindOf(stage) : "active");
  }, [open, stage]);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSave({ name: name.trim(), description, color, is_backlog: kind === "backlog", is_completed: kind === "completed" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't work.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={stage ? `Edit ${stage.name}` : "New stage"}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy || !name.trim()} onClick={save}>
            Save
          </button>
        </>
      }
    >
      {error && <p className="tone-danger mb-3 rounded-[5px] px-3 py-2 text-sm">{error}</p>}
      <div className="grid gap-4">
        <Labeled label="Name">
          <input className="field" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </Labeled>
        <Labeled label="Description">
          <input className="field" value={description} onChange={(e) => setDescription(e.target.value)} />
        </Labeled>
        <ColorPicker value={color} onChange={setColor} />
        <fieldset className="grid gap-2 text-sm">
          <legend className="mb-1 text-xs font-medium text-[var(--text-muted)]">Counts as</legend>
          {(["backlog", "active", "completed"] as Kind[]).map((k) => (
            <label key={k} className="flex items-center gap-2">
              <input type="radio" name="kind" checked={kind === k} onChange={() => setKind(k)} />
              {KIND_LABEL[k]}
              <span className="text-xs text-[var(--text-muted)]">
                {k === "completed" ? "the ticket is resolved and its SLA stops" : k === "backlog" ? "not yet picked up" : "someone is working on it"}
              </span>
            </label>
          ))}
        </fieldset>
      </div>
    </Modal>
  );
}
