"use client";

// The workflow editor's dialogs: a status, a transition, the status order, and deleting either.

import { useEffect, useState } from "react";
import Modal, { Labeled, Tabs } from "@/components/Modal";
import StatusChip from "@/components/StatusChip";
import { ActionsEditor, RulesEditor, cleanActions, cleanRules, type ActionContext } from "@/components/workflow/Editors";
import { api, ApiError } from "@/lib/api";
import {
  PALETTE,
  POINTS,
  POINT_PLACEMENT,
  type Action,
  type Catalog,
  type Point,
  type Rule,
  type Stage,
  type Status,
  type Transition,
  type WorkflowDetail,
} from "@/lib/lifecycle";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Checkbox } from "@/components/ui/checkbox";

function useSubmit(onDone: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't work.");
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, submit, setError };
}

function ErrorLine({ error }: { error: string | null }) {
  return error ? <Alert variant="danger" className="mb-3 text-sm"><AlertDescription>{error}</AlertDescription></Alert> : null;
}

export function StatusDialog({
  open,
  onClose,
  onSaved,
  workflow,
  status,
  stages,
  catalog,
  context,
  at,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  workflow: WorkflowDetail;
  status: Status | null;
  stages: Stage[];
  catalog: Catalog;
  context: ActionContext;
  at?: { x: number; y: number };
}) {
  const [tab, setTab] = useState<"info" | "actions">("info");
  const [name, setName] = useState("");
  const [base, setBase] = useState("");
  const [color, setColor] = useState(PALETTE[0]);
  const [actions, setActions] = useState<Action[]>([]);
  const { busy, error, submit, setError } = useSubmit(onSaved);

  useEffect(() => {
    if (!open) return;
    setTab("info");
    setError(null);
    setName(status?.name ?? "");
    setBase(status?.base.id ?? stages.find((s) => !s.is_backlog && !s.is_completed)?.id ?? stages[0]?.id ?? "");
    setColor(status?.color || PALETTE[0]);
    setActions(status?.actions ?? []);
  }, [open, status, stages, setError]);

  const locked = !!status?.is_pipeline;
  const save = () =>
    submit(() => {
      const body = { name: name.trim(), base_id: base, color, ...(locked ? {} : { actions: cleanActions(actions) }) };
      if (status) return api.patch(`/api/lifecycle/statuses/${status.id}`, body);
      const coordinates = at ? `${Math.round(at.x)}|${Math.round(at.y)}` : undefined;
      return api.post(`/api/lifecycle/workflows/${workflow.id}/statuses`, { ...body, coordinates });
    });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={status ? `Edit ${status.name}` : "Add a status"}
      subtitle={locked ? "A triage status: you can rename and recolour it, but only the pipeline moves tickets into it." : undefined}
      width="max-w-2xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={busy || !name.trim() || !base} onClick={save}>
            {status ? "Save" : "Add status"}
          </Button>
        </>
      }
    >
      <ErrorLine error={error} />
      {!locked && (
        <Tabs
          value={tab}
          onChange={setTab}
          tabs={[
            { key: "info", label: "Status" },
            { key: "actions", label: "On enter", count: actions.length },
          ]}
        />
      )}
      {tab === "info" ? (
        <div className="grid gap-4">
          <Labeled label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Waiting on vendor" autoFocus />
          </Labeled>
          <Labeled label="Stage" hint="The system stage this status reports as. A resolved stage stops the SLA clock.">
            <NativeSelect value={base} onChange={(e) => setBase(e.target.value)} disabled={locked}>
              {stages.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                  {s.is_completed ? " (resolved)" : s.is_backlog ? " (backlog)" : ""}
                </option>
              ))}
            </NativeSelect>
          </Labeled>
          <ColorPicker value={color} onChange={setColor} />
        </div>
      ) : (
        <ActionsEditor actions={actions} onChange={setActions} catalog={catalog} where="status" context={context} />
      )}
    </Modal>
  );
}

export function ColorPicker({ value, onChange }: { value: string; onChange: (c: string) => void }) {
  return (
    <div className="flex flex-col gap-1.5 text-sm">
      <span className="text-xs font-medium text-muted-foreground">Colour</span>
      <div className="flex flex-wrap items-center gap-2">
        {PALETTE.map((c) => (
          <button
            key={c}
            type="button"
            aria-label={c}
            onClick={() => onChange(c)}
            className={`h-7 w-7 rounded-full border-2 ${value.toLowerCase() === c ? "border-foreground" : "border-transparent"}`}
            style={{ background: c }}
          />
        ))}
        <Input className="w-28 font-mono text-[13px]" value={value} onChange={(e) => onChange(e.target.value)} aria-label="Hex colour" />
      </div>
    </div>
  );
}

export interface TransitionDraft {
  from?: string;
  to?: string;
  pointStart?: Point;
  pointEnd?: Point;
}

export function TransitionDialog({
  open,
  onClose,
  onSaved,
  workflow,
  transition,
  draft,
  catalog,
  context,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  workflow: WorkflowDetail;
  transition: Transition | null;
  draft?: TransitionDraft;
  catalog: Catalog;
  context: ActionContext;
}) {
  const [tab, setTab] = useState<"info" | "rules" | "actions">("info");
  const [name, setName] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [pointStart, setPointStart] = useState<Point>("3");
  const [pointEnd, setPointEnd] = useState<Point>("7");
  const [both, setBoth] = useState(false);
  const [rules, setRules] = useState<Rule[]>([]);
  const [actions, setActions] = useState<Action[]>([]);
  const { busy, error, submit, setError } = useSubmit(onSaved);

  useEffect(() => {
    if (!open) return;
    setTab("info");
    setError(null);
    setName(transition?.name ?? "");
    setFrom(transition?.from_status_id ?? draft?.from ?? "");
    setTo(transition?.to_status_id ?? draft?.to ?? "");
    setPointStart(transition?.point_start ?? draft?.pointStart ?? "3");
    setPointEnd(transition?.point_end ?? draft?.pointEnd ?? "7");
    setBoth(transition?.is_bidirectional ?? false);
    setRules(transition?.rules ?? []);
    setActions(transition?.actions ?? []);
  }, [open, transition, draft, setError]);

  const statuses = [...workflow.statuses].sort((a, b) => a.order - b.order);
  const byId = Object.fromEntries(statuses.map((s) => [s.id, s]));
  const fromStatus = byId[from];
  const toStatus = byId[to];

  useEffect(() => {
    if (open && !transition && fromStatus && toStatus && !name) setName(`${fromStatus.name} → ${toStatus.name}`);
  }, [from, to]);

  const save = () =>
    submit(() => {
      const body = {
        name: name.trim(),
        point_start: pointStart,
        point_end: pointEnd,
        is_bidirectional: both,
        rules: cleanRules(rules),
        actions: cleanActions(actions),
      };
      if (transition) return api.patch(`/api/lifecycle/transitions/${transition.id}`, body);
      return api.post(`/api/lifecycle/workflows/${workflow.id}/transitions`, { ...body, from_status_id: from, to_status_id: to });
    });

  const used = (statusId: string, except?: string) =>
    new Set(
      workflow.transitions
        .filter((t) => t.id !== except)
        .flatMap((t) => [t.from_status_id === statusId ? t.point_start : null, t.to_status_id === statusId ? t.point_end : null])
        .filter(Boolean) as Point[],
    );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={transition ? `Edit ${transition.name}` : "Add a transition"}
      subtitle={
        fromStatus && toStatus ? (
          <span className="inline-flex items-center gap-2">
            <StatusChip name={fromStatus.name} color={fromStatus.color} />
            <span>{both ? "↔" : "→"}</span>
            <StatusChip name={toStatus.name} color={toStatus.color} />
          </span>
        ) : undefined
      }
      width="max-w-2xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={busy || !name.trim() || !from || !to || from === to} onClick={save}>
            {transition ? "Save" : "Add transition"}
          </Button>
        </>
      }
    >
      <ErrorLine error={error} />
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "info", label: "Transition" },
          { key: "rules", label: "Checks", count: rules.length },
          { key: "actions", label: "Actions", count: actions.length },
        ]}
      />
      {tab === "info" && (
        <div className="grid gap-4">
          <Labeled label="Name" hint="The button people see on the ticket.">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Start work" />
          </Labeled>
          <div className="grid gap-4 sm:grid-cols-2">
            <Labeled label="From">
              <NativeSelect value={from} onChange={(e) => setFrom(e.target.value)} disabled={!!transition}>
                <option value="">Choose…</option>
                {statuses.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </NativeSelect>
            </Labeled>
            <Labeled label="To">
              <NativeSelect value={to} onChange={(e) => setTo(e.target.value)} disabled={!!transition}>
                <option value="">Choose…</option>
                {statuses
                  .filter((s) => !s.is_pipeline && s.id !== from)
                  .map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
              </NativeSelect>
            </Labeled>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <PointPicker label="Leaves from" color={fromStatus?.color} value={pointStart} onChange={setPointStart} taken={from ? used(from, transition?.id) : new Set()} />
            <PointPicker label="Arrives at" color={toStatus?.color} value={pointEnd} onChange={setPointEnd} taken={to ? used(to, transition?.id) : new Set()} />
          </div>
          <label className="flex items-start gap-2 text-sm">
            <Checkbox className="mt-0.5" checked={both} onCheckedChange={(checked) => setBoth(checked === true)} disabled={!!fromStatus?.is_pipeline} />
            <span>
              Both ways
              <span className="block text-xs text-muted-foreground">
                {fromStatus?.is_pipeline ? "Not possible from a triage status: only the pipeline moves tickets into it." : "Tickets can also move back along this transition."}
              </span>
            </span>
          </label>
        </div>
      )}
      {tab === "rules" && (
        <>
          <p className="mb-3 text-sm text-muted-foreground">Every check must pass before the ticket moves. A failing check names the field to fix.</p>
          <RulesEditor rules={rules} onChange={setRules} catalog={catalog} fields={workflow.fields} />
        </>
      )}
      {tab === "actions" && (
        <>
          <p className="mb-3 text-sm text-muted-foreground">
            Run in order. A failing action before the move stops it; after the move, it is recorded on the ticket for a retry.
          </p>
          <ActionsEditor actions={actions} onChange={setActions} catalog={catalog} where="transition" context={context} />
        </>
      )}
    </Modal>
  );
}

function PointPicker({
  label,
  value,
  onChange,
  taken,
  color,
}: {
  label: string;
  value: Point;
  onChange: (p: Point) => void;
  taken: Set<Point>;
  color?: string;
}) {
  const W = 168,
    H = 96,
    P = 14;
  const xy = (p: Point) => {
    const { side, at } = POINT_PLACEMENT[p];
    const w = W - 2 * P,
      h = H - 2 * P;
    if (side === "top") return { x: P + (w * at) / 100, y: P };
    if (side === "bottom") return { x: P + (w * at) / 100, y: H - P };
    if (side === "left") return { x: P, y: P + (h * at) / 100 };
    return { x: W - P, y: P + (h * at) / 100 };
  };
  return (
    <div className="flex flex-col gap-1 text-sm">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-[168px]" role="radiogroup" aria-label={label}>
        <rect x={P} y={P} width={W - 2 * P} height={H - 2 * P} rx={6} fill="var(--muted)" stroke={color || "var(--border-strong)"} />
        {POINTS.map((p) => {
          const { x, y } = xy(p);
          const selected = value === p;
          const isTaken = taken.has(p) && !selected;
          return (
            <g key={p} role="radio" aria-checked={selected} aria-label={`Point ${p}${isTaken ? " (in use)" : ""}`} onClick={() => onChange(p)} className="cursor-pointer">
              <circle cx={x} cy={y} r={9} fill="transparent" />
              <circle
                cx={x}
                cy={y}
                r={selected ? 6 : 4.5}
                fill={selected ? color || "var(--foreground)" : isTaken ? "var(--border-strong)" : "var(--card)"}
                stroke={selected ? "var(--card)" : "var(--muted-foreground)"}
                strokeWidth={selected ? 2 : 1}
              />
            </g>
          );
        })}
      </svg>
      <span className="text-xs text-muted-foreground">Grey points are used by other transitions.</span>
    </div>
  );
}

export function ReorderDialog({
  open,
  onClose,
  onSaved,
  workflow,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  workflow: WorkflowDetail;
}) {
  const [order, setOrder] = useState<Status[]>([]);
  const { busy, error, submit } = useSubmit(onSaved);
  useEffect(() => {
    if (open) setOrder([...workflow.statuses].sort((a, b) => a.order - b.order));
  }, [open, workflow]);
  const move = (i: number, d: number) => {
    const next = [...order];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    setOrder(next);
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Status order"
      subtitle="The order of the board's columns and of status lists."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={busy}
            onClick={() => submit(() => api.post(`/api/lifecycle/workflows/${workflow.id}/statuses/reorder`, { ids: order.map((s) => s.id) }))}
          >
            Save order
          </Button>
        </>
      }
    >
      <ErrorLine error={error} />
      <ol className="flex flex-col gap-1">
        {order.map((s, i) => (
          <li key={s.id} className="flex items-center gap-3 rounded-md border border-border px-3 py-2">
            <span className="w-5 text-xs text-muted-foreground">{i + 1}</span>
            <span className="flex-1">
              <StatusChip name={s.name} color={s.color} />
            </span>
            <span className="text-xs text-muted-foreground">{s.base.name}</span>
            <Button variant="outline" size="sm" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Move ${s.name} up`}>
              ↑
            </Button>
            <Button variant="outline" size="sm" disabled={i === order.length - 1} onClick={() => move(i, 1)} aria-label={`Move ${s.name} down`}>
              ↓
            </Button>
          </li>
        ))}
      </ol>
    </Modal>
  );
}

export function DeleteDialog({
  open,
  onClose,
  onDeleted,
  workflow,
  status,
  transition,
}: {
  open: boolean;
  onClose: () => void;
  onDeleted: () => void;
  workflow: WorkflowDetail;
  status?: Status | null;
  transition?: Transition | null;
}) {
  const [migrateTo, setMigrateTo] = useState("");
  const { busy, error, submit } = useSubmit(onDeleted);
  useEffect(() => {
    if (open) setMigrateTo("");
  }, [open]);
  const targets = workflow.statuses.filter((s) => !s.is_pipeline && s.id !== status?.id);
  const touching = status ? workflow.transitions.filter((t) => t.from_status_id === status.id || t.to_status_id === status.id).length : 0;
  const what = status ? status.name : transition?.name ?? "";

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Delete ${what}?`}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="destructive"
            disabled={busy}
            onClick={() =>
              submit(() =>
                status
                  ? api.delete(`/api/lifecycle/statuses/${status.id}${migrateTo ? `?migrate_to=${migrateTo}` : ""}`)
                  : api.delete(`/api/lifecycle/transitions/${transition!.id}`),
              )
            }
          >
            Delete
          </Button>
        </>
      }
    >
      <ErrorLine error={error} />
      {status ? (
        <div className="grid gap-4 text-sm">
          <p>
            {touching > 0
              ? `Its ${touching} transition${touching === 1 ? "" : "s"} will be deleted with it.`
              : "No transitions use this status."}
          </p>
          <Labeled label="Move its tickets to" hint="Required if any ticket is in this status now.">
            <NativeSelect value={migrateTo} onChange={(e) => setMigrateTo(e.target.value)}>
              <option value="">No tickets to move</option>
              {targets.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </NativeSelect>
          </Labeled>
        </div>
      ) : (
        <p className="text-sm">
          {workflow.transition_policy === "open"
            ? "The move stays allowed, but its checks and actions stop applying."
            : "People will no longer be able to make this move."}
        </p>
      )}
    </Modal>
  );
}
