"use client";

// Rollout (F9 · Rollout 16-1179, Flag request 16-1328): each automated branch is live only when the
// env isn't shadow, its flag is on and the thresholds are approved (BR-F9-01).

import { useCallback, useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { FlagOut, GateValueOut, RolloutOut } from "@/lib/types/generated";

const GATE_TEXT: Record<string, string> = {
  auto_route: "P3 gate: reroute rate < 15 % over 14 days on shadow auto_route decisions",
  auto_reply: "P4 gate: precision ≥ 0.95 on the calibration holdout and ≥ 3 approved low-risk pages",
  requester_questions: "Gate: clarify agreement ≥ 0.80 over 14 days",
};

function pct(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)} %`;
}

function gateValue(g: GateValueOut): string {
  if (g.value === null) return `${g.metric}: no data`;
  if (g.metric === "approved_low_pages") return `low pages ${g.value}`;
  if (g.metric === "holdout_precision") return `precision ${g.value.toFixed(3)}`;
  return `${g.metric.replace("_", " ")} ${pct(g.value)}`;
}

type Dialog =
  | { kind: "request"; flag: FlagOut }
  | { kind: "approve"; flag: FlagOut }
  | { kind: "reject"; flag: FlagOut }
  | { kind: "off"; flag: FlagOut }
  | null;

export default function RolloutPage() {
  const user = useRequireAuth();
  const [data, setData] = useState<RolloutOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [reason, setReason] = useState("");
  const [override, setOverride] = useState("");
  const [precision, setPrecision] = useState("");
  const [evidence, setEvidence] = useState("");
  const [busy, setBusy] = useState(false);
  const [gateEdits, setGateEdits] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      setData(await api.get<RolloutOut>("/api/rollout"));
    } catch {
      setError("Couldn't load the rollout state.");
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;
  if (!data) return <p className="text-sm text-[var(--text-muted)]">{error ?? "Loading…"}</p>;

  const isManager = user.role === "manager";
  const mayTurnOff = isManager || user.role === "security";

  const open = (d: Dialog) => {
    setDialog(d);
    setReason("");
    setOverride("");
    setPrecision("");
    setEvidence("");
    setError(null);
  };

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setDialog(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? `${err.code ?? "refused"}: ${err.message}` : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const submit = () => {
    if (!dialog) return;
    const branch = dialog.flag.branch;
    const pending = dialog.flag.pending;
    if (dialog.kind === "request")
      return run(() =>
        api.post(`/api/rollout/${branch}/requests`, {
          reason,
          gate_override_reason: override,
          entered_values:
            branch === "auto_reply" && precision ? { holdout_precision: { value: Number(precision), evidence } } : {},
        }),
      );
    if (dialog.kind === "approve" && pending)
      return run(() => api.post(`/api/rollout/requests/${pending.id}/approve`, { gate_override_reason: override }));
    if (dialog.kind === "reject" && pending) return run(() => api.post(`/api/rollout/requests/${pending.id}/reject`, { reason }));
    if (dialog.kind === "off") return run(() => api.post(`/api/rollout/${branch}/off`, { reason }));
  };

  const unmet = dialog ? dialog.flag.gates.some((g) => !g.met) : false;
  const needsReason = dialog?.kind === "request" || dialog?.kind === "reject" || dialog?.kind === "off";

  return (
    <div className="mx-auto flex max-w-[1080px] flex-col gap-4">
      <header>
        <h1 className="text-xl font-semibold">Rollout</h1>
        <p className="text-xs text-[var(--text-muted)]">
          A branch is live only when all three keys turn: env not shadow, branch flag on, thresholds approved (BR-F9-01).
        </p>
      </header>
      {error && !dialog && <p className="text-sm text-[var(--danger)]">{error}</p>}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <Card label="Env SHADOW_MODE" value={String(data.env_shadow)} note="set in .env at deploy" />
        <Card
          label="Thresholds"
          value={data.thresholds.change_request ?? data.thresholds.version}
          note={`${data.thresholds.approved ? "approved" : "NOT approved"}${data.thresholds.checked ? "" : " (check off)"} · sha256 ${data.thresholds.sha256.slice(0, 8)}…`}
          warn={!data.thresholds.approved}
        />
        <Card label="Router" value="unchanged" note="flags never change the branch chosen" />
      </div>

      {data.flags.map((flag) => (
        <section key={flag.branch} className="card flex flex-col gap-3 p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2 font-semibold">
                <span className="font-mono">{flag.branch}</span>
                <FlagChip flag={flag} />
                {flag.state === "on" && !flag.live && <span className="badge tone-warn">not live: {data.env_shadow ? "env shadow" : "thresholds"}</span>}
              </h2>
              <p className="text-xs text-[var(--text-muted)]">{GATE_TEXT[flag.branch]}</p>
            </div>
            <div className="flex gap-2">
              {flag.state !== "off" && mayTurnOff && (
                <button className="btn btn-danger" onClick={() => open({ kind: "off", flag })}>
                  Turn off
                </button>
              )}
              {flag.state === "off" && isManager && (
                <button className="btn btn-primary" onClick={() => open({ kind: "request", flag })}>
                  Request on…
                </button>
              )}
              {flag.pending && isManager && flag.pending.requested_by !== user.username && (
                <>
                  <button className="btn btn-secondary" onClick={() => open({ kind: "reject", flag })}>
                    Reject
                  </button>
                  <button className="btn btn-primary" onClick={() => open({ kind: "approve", flag })}>
                    Approve{flag.gates.some((g) => !g.met) ? " (override)" : ""}…
                  </button>
                </>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-8 text-sm">
            <div>
              <p className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">Gate value</p>
              <p className="mt-1 flex flex-wrap items-center gap-2">
                {flag.gates.map((g) => (
                  <span key={g.metric} className="flex items-center gap-1.5">
                    {gateValue(g)}
                    <span className={`badge ${g.met ? "tone-ok" : "tone-danger"}`}>{g.met ? "met" : "not met"}</span>
                  </span>
                ))}
              </p>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">Shadow agreement (14 days)</p>
              <p className="mt-1">
                {pct(flag.agreement)} {flag.agreement_decided > 0 && <span className="text-xs text-[var(--text-muted)]">of {flag.agreement_decided} decided</span>}
              </p>
            </div>
          </div>
          {flag.pending && (
            <p className="rounded-[5px] bg-[var(--surface-2)] px-3 py-2 text-xs">
              Requested by {flag.pending.requested_by}: “{flag.pending.reason}” · approvals{" "}
              {flag.pending.approvals.map((a) => String(a.user)).join(", ") || "none yet"} ({flag.pending.approvals.length} of 2) ·
              expires {new Date(flag.pending.expires_at).toLocaleString()}
            </p>
          )}
        </section>
      ))}

      <section className="card p-5">
        <h2 className="mb-2 text-sm font-semibold">Gates</h2>
        <p className="mb-3 text-xs text-[var(--text-muted)]">A change waits for a second manager (AC-F9-08).</p>
        <table className="w-full text-left text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
            <tr>
              <th className="py-1.5 font-medium">Branch</th>
              <th className="py-1.5 font-medium">Metric</th>
              <th className="py-1.5 font-medium">Threshold</th>
              <th className="py-1.5 font-medium">Window</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.gates.map((g) => {
              const pending = data.gate_changes.find((c) => c.gate === g.id);
              return (
                <tr key={g.id} className="border-t border-[var(--border)]">
                  <td className="py-2 font-mono text-xs">{g.branch}</td>
                  <td className="py-2">{g.metric}</td>
                  <td className="py-2">
                    {g.comparator === "lt" ? "<" : "≥"} {g.threshold}
                    {pending && <span className="ml-2 text-xs text-[var(--warn)]">→ {pending.threshold} pending ({pending.requested_by})</span>}
                  </td>
                  <td className="py-2">{g.window_days ? `${g.window_days} d` : "—"}</td>
                  <td className="py-2 text-right">
                    {isManager && pending && pending.requested_by !== user.username && (
                      <>
                        <button className="mr-2 text-xs text-[var(--accent)]" onClick={() => run(() => api.post(`/api/rollout/gate-changes/${pending.id}/approve`))}>
                          Approve
                        </button>
                        <button className="text-xs text-[var(--danger)]" onClick={() => run(() => api.post(`/api/rollout/gate-changes/${pending.id}/reject`))}>
                          Reject
                        </button>
                      </>
                    )}
                    {isManager && !pending && (
                      <span className="flex justify-end gap-1">
                        <input
                          className="field w-20 py-0.5 text-xs"
                          placeholder={String(g.threshold)}
                          value={gateEdits[g.id] ?? ""}
                          onChange={(e) => setGateEdits({ ...gateEdits, [g.id]: e.target.value })}
                        />
                        <button
                          className="text-xs text-[var(--accent)] disabled:opacity-40"
                          disabled={!gateEdits[g.id]}
                          onClick={() => {
                            const why = window.prompt("Reason for the gate change");
                            if (!why) return;
                            void run(() =>
                              api.patch(`/api/rollout/gates/${g.id}`, {
                                threshold: Number(gateEdits[g.id]),
                                window_days: g.window_days,
                                reason: why,
                              }),
                            ).then(() => setGateEdits({ ...gateEdits, [g.id]: "" }));
                          }}
                        >
                          Propose
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <p className="text-xs text-[var(--text-muted)]">
        No flag exists for runbooks: they always go to a person (ADR-0006, BR-F9-10). Turning off needs one manager or security and is
        instant.
      </p>

      <Modal
        open={dialog !== null}
        onClose={() => setDialog(null)}
        title={
          dialog?.kind === "request"
            ? `Request ${dialog.flag.branch} on`
            : dialog?.kind === "approve"
              ? `Approve ${dialog.flag.branch}`
              : dialog?.kind === "reject"
                ? `Reject the ${dialog.flag.branch} request`
                : `Turn ${dialog?.flag.branch} off now`
        }
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => setDialog(null)}>
              Cancel
            </button>
            <button
              className={dialog?.kind === "off" ? "btn btn-danger" : "btn btn-primary"}
              disabled={busy || (needsReason && !reason.trim()) || (dialog?.kind === "approve" && unmet && !override.trim())}
              onClick={() => void submit()}
            >
              {dialog?.kind === "off" ? "Tắt ngay · Turn off" : dialog?.kind === "reject" ? "Reject" : dialog?.kind === "approve" ? "Approve" : "Request"}
            </button>
          </>
        }
      >
        {dialog && (
          <div className="flex flex-col gap-3 text-sm">
            <ul className="rounded-[5px] border border-[var(--border)] px-3 py-2 text-xs">
              {dialog.flag.gates.map((g) => (
                <li key={g.metric}>
                  {gateValue(g)} — {g.comparator === "lt" ? "<" : "≥"} {g.threshold}: <strong>{g.met ? "met" : "not met"}</strong>
                </li>
              ))}
            </ul>
            {dialog.kind === "request" && dialog.flag.branch === "auto_reply" && (
              <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-2">
                <input className="field" placeholder="0.95" value={precision} onChange={(e) => setPrecision(e.target.value)} aria-label="Holdout precision" />
                <input className="field" placeholder="Evidence: eval run / HISTORY.md entry" value={evidence} onChange={(e) => setEvidence(e.target.value)} />
              </div>
            )}
            {needsReason && (
              <label className="flex flex-col gap-1">
                <span className="text-xs text-[var(--text-muted)]">Reason (required)</span>
                <textarea className="field min-h-[64px]" value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
            )}
            {(dialog.kind === "approve" || dialog.kind === "request") && (
              <label className="flex flex-col gap-1">
                <span className="text-xs text-[var(--text-muted)]">
                  Gate override reason {dialog.kind === "approve" && unmet ? "(required: a gate isn't met)" : "(only if a gate isn't met)"}
                </span>
                <input className="field" value={override} onChange={(e) => setOverride(e.target.value)} />
              </label>
            )}
            {dialog.kind === "approve" && (
              <p className="text-xs text-[var(--text-muted)]">
                Turning automation on takes two managers, neither the requester (BR-F9-02).
              </p>
            )}
            {error && <p className="text-[var(--danger)]">{error}</p>}
          </div>
        )}
      </Modal>
    </div>
  );
}

function Card({ label, value, note, warn = false }: { label: string; value: string; note: string; warn?: boolean }) {
  return (
    <div className={`card p-4 ${warn ? "border-[var(--danger)]" : ""}`}>
      <p className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">{label}</p>
      <p className={`mt-1 text-xl font-semibold ${warn ? "text-[var(--danger)]" : ""}`}>{value}</p>
      <p className="text-xs text-[var(--text-muted)]">{note}</p>
    </div>
  );
}

function FlagChip({ flag }: { flag: FlagOut }) {
  if (flag.state === "on") return <span className="badge tone-ok">on</span>;
  if (flag.state === "pending_on")
    return <span className="badge tone-warn">pending_on · {flag.pending?.approvals.length ?? 0} of 2 approvals</span>;
  return <span className="badge">off</span>;
}
