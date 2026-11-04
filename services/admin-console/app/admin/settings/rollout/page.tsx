"use client";

// Rollout (F9 · Rollout 16-1179): each automated branch is live only when the env isn't shadow, its
// flag is on and the thresholds are approved (BR-F9-01); one manager turns a flag on (ADR-0043).

import { useCallback, useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { FlagOut, GateValueOut, RolloutOut } from "@/lib/types/generated";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SectionTabs } from "@/components/TabNav";

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

type Dialog = { kind: "on"; flag: FlagOut } | { kind: "off"; flag: FlagOut } | null;

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
  if (!data) return <p className="text-sm text-muted-foreground">{error ?? "Loading…"}</p>;

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
    if (dialog.kind === "on")
      return run(() =>
        api.post(`/api/rollout/${branch}/on`, {
          reason,
          gate_override_reason: override,
          entered_values:
            branch === "auto_reply" && precision ? { holdout_precision: { value: Number(precision), evidence } } : {},
        }),
      );
    if (dialog.kind === "off") return run(() => api.post(`/api/rollout/${branch}/off`, { reason }));
  };

  const unmet = dialog ? dialog.flag.gates.some((g) => !g.met) : false;

  return (
    <div className="mx-auto flex max-w-[1080px] flex-col gap-4">
      <SectionTabs className="mb-1" />
      <header>
        <h1 className="text-xl font-semibold">Rollout</h1>
        <p className="text-xs text-muted-foreground">
          A branch is live only when both keys turn: env not shadow and the branch flag on (BR-F9-01).
        </p>
      </header>
      {error && !dialog && <p className="text-sm text-danger">{error}</p>}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <StatCard label="Env SHADOW_MODE" value={String(data.env_shadow)} note="set in .env at deploy" />
        <StatCard label="Thresholds" value={data.thresholds} note="the loaded thresholds.yaml version" />
        <StatCard label="Router" value="unchanged" note="flags never change the branch chosen" />
      </div>

      {data.flags.map((flag) => (
        <Card asChild key={flag.branch}>
          <section className="flex flex-col gap-3 p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="flex items-center gap-2 font-semibold">
                  <span className="font-mono">{flag.branch}</span>
                  <FlagChip flag={flag} />
                  {flag.state === "on" && !flag.live && <Badge variant="warn">not live: env shadow</Badge>}
                </h2>
                <p className="text-xs text-muted-foreground">{GATE_TEXT[flag.branch]}</p>
              </div>
              <div className="flex gap-2">
                {flag.state !== "off" && mayTurnOff && (
                  <Button variant="destructive" onClick={() => open({ kind: "off", flag })}>
                    Turn off
                  </Button>
                )}
                {flag.state === "off" && isManager && (
                  <Button onClick={() => open({ kind: "on", flag })}>
                    Turn on{flag.gates.some((g) => !g.met) ? " (override)" : ""}…
                  </Button>
                )}
              </div>
            </div>
            <div className="flex flex-wrap gap-8 text-sm">
              <div>
                <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Gate value</p>
                <p className="mt-1 flex flex-wrap items-center gap-2">
                  {flag.gates.map((g) => (
                    <span key={g.metric} className="flex items-center gap-1.5">
                      {gateValue(g)}
                      <Badge variant={g.met ? "ok" : "danger"}>{g.met ? "met" : "not met"}</Badge>
                    </span>
                  ))}
                </p>
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Shadow agreement (14 days)</p>
                <p className="mt-1">
                  {pct(flag.agreement)} {flag.agreement_decided > 0 && <span className="text-xs text-muted-foreground">of {flag.agreement_decided} decided</span>}
                </p>
              </div>
            </div>
            {flag.changed_by && (
              <p className="text-xs text-muted-foreground">
                Turned {flag.state} by {flag.changed_by}
                {flag.changed_at ? ` on ${new Date(flag.changed_at).toLocaleString()}` : ""}
                {flag.reason ? `: “${flag.reason}”` : ""}
              </p>
            )}
          </section>
        </Card>
      ))}

      <Card asChild>
        <section className="p-5">
          <h2 className="mb-2 text-sm font-semibold">Gates</h2>
          <p className="mb-3 text-xs text-muted-foreground">A manager's change applies at once, with a reason (AC-F9-08).</p>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="py-1.5">Branch</TableHead>
                <TableHead className="py-1.5">Metric</TableHead>
                <TableHead className="py-1.5">Threshold</TableHead>
                <TableHead className="py-1.5">Window</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.gates.map((g) => {
                return (
                  <TableRow key={g.id}>
                    <TableCell className="py-2 font-mono text-xs">{g.branch}</TableCell>
                    <TableCell className="py-2">{g.metric}</TableCell>
                    <TableCell className="py-2">
                      {g.comparator === "lt" ? "<" : "≥"} {g.threshold}
                    </TableCell>
                    <TableCell className="py-2">{g.window_days ? `${g.window_days} d` : "—"}</TableCell>
                    <TableCell className="py-2 text-right">
                      {isManager && (
                        <span className="flex justify-end gap-1">
                          <Input
                            className="w-20 py-0.5 text-xs"
                            placeholder={String(g.threshold)}
                            value={gateEdits[g.id] ?? ""}
                            onChange={(e) => setGateEdits({ ...gateEdits, [g.id]: e.target.value })}
                          />
                          <Button variant="link" size="inline"
                            className="text-xs disabled:opacity-40"
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
                            Save
                          </Button>
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </section>
      </Card>

      <p className="text-xs text-muted-foreground">
        No flag exists for runbooks: they always go to a person (ADR-0006, BR-F9-10). One manager turns a branch on; one manager or
        security turns it off. Both are instant.
      </p>

      <Modal
        open={dialog !== null}
        onClose={() => setDialog(null)}
        title={dialog?.kind === "on" ? `Turn ${dialog.flag.branch} on now` : `Turn ${dialog?.flag.branch} off now`}
        footer={
          <>
            <Button variant="outline" onClick={() => setDialog(null)}>
              Cancel
            </Button>
            <Button
              variant={dialog?.kind === "off" ? "destructive" : "default"}
              disabled={busy || !reason.trim() || (dialog?.kind === "on" && unmet && !override.trim())}
              onClick={() => void submit()}
            >
              {dialog?.kind === "off" ? "Tắt ngay · Turn off" : "Bật ngay · Turn on"}
            </Button>
          </>
        }
      >
        {dialog && (
          <div className="flex flex-col gap-3 text-sm">
            <ul className="rounded-md border border-border px-3 py-2 text-xs">
              {dialog.flag.gates.map((g) => (
                <li key={g.metric}>
                  {gateValue(g)} — {g.comparator === "lt" ? "<" : "≥"} {g.threshold}: <strong>{g.met ? "met" : "not met"}</strong>
                </li>
              ))}
            </ul>
            {dialog.kind === "on" && dialog.flag.branch === "auto_reply" && (
              <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-2">
                <Input placeholder="0.95" value={precision} onChange={(e) => setPrecision(e.target.value)} aria-label="Holdout precision" />
                <Input placeholder="Evidence: eval run / HISTORY.md entry" value={evidence} onChange={(e) => setEvidence(e.target.value)} />
              </div>
            )}
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Reason (required)</span>
              <Textarea className="min-h-[64px]" value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            {dialog.kind === "on" && unmet && (
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Gate override reason (required: a gate isn't met)</span>
                <Input value={override} onChange={(e) => setOverride(e.target.value)} />
              </label>
            )}
            {dialog.kind === "on" && (
              <p className="text-xs text-muted-foreground">The branch acts live as soon as you turn it on, if the env isn't shadow.</p>
            )}
            {error && <p className="text-danger">{error}</p>}
          </div>
        )}
      </Modal>
    </div>
  );
}

function StatCard({ label, value, note, warn = false }: { label: string; value: string; note: string; warn?: boolean }) {
  return (
    <Card className={`p-4 ${warn ? "border-danger" : ""}`}>
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`mt-1 text-xl font-semibold ${warn ? "text-danger" : ""}`}>{value}</p>
      <p className="text-xs text-muted-foreground">{note}</p>
    </Card>
  );
}

function FlagChip({ flag }: { flag: FlagOut }) {
  if (flag.state === "on") return <Badge variant="ok">on</Badge>;
  return <Badge variant="neutral">off</Badge>;
}
