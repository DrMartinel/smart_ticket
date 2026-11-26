"use client";

// The assistant's changes to one cloud resource (F17 BR-F17-08, ADR-0046 §7–8): a change waiting
// for the person's confirmation, sent exactly as proposed, or a draft the person applies, changed
// first if they choose. A change whose answer was lost is never offered again (BR-F17-09).

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Bot } from "lucide-react";
import { agentApi } from "@/lib/agent";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { relativeTime } from "@/lib/format";
import { CHANGE_LABEL, OUTCOME_UNKNOWN_TEXT, RESOURCE_LABEL, changeOf, changeRefusal, describeRule, type ResourceKind } from "@/lib/infra";
import { P, can } from "@/lib/permissions";
import type { AgentActionOut, RuleOut, SecurityRuleIn } from "@/lib/types/generated";
import { Labeled } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Panel } from "@/components/ui/panel";
import { useToast } from "@/components/ui/toast";

type Payload = Record<string, unknown>;
type Lost = { action: AgentActionOut; text: string };

const payloadOf = (action: AgentActionOut): Payload => ({ ...((action.arguments.payload ?? {}) as Payload) });

export default function ResourceChanges({
  kind,
  id,
  name,
  rules = [],
  onChanged,
}: {
  kind: ResourceKind;
  id: string;
  name: string;
  // A security group's rules, to name the one a removal drafts.
  rules?: RuleOut[];
  // Reads the resource again after a change was sent or refused for its state.
  onChanged: () => void;
}) {
  const { user } = useAuth();
  const toast = useToast();
  const [pending, setPending] = useState<AgentActionOut[]>([]);
  const [lost, setLost] = useState<Lost[]>([]);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [edits, setEdits] = useState<Record<string, Payload>>({});
  const usesAgent = can(user, P.agentUse);
  const operates = can(user, P.infraOperate);

  const load = useCallback(async () => {
    const onThis = (a: AgentActionOut) => a.target_kind === kind && a.target_ref === id;
    try {
      const [waiting, unknown] = await Promise.all([agentApi.actions("state=pending"), agentApi.actions("state=outcome_unknown")]);
      setPending(waiting.filter(onThis));
      setLost(unknown.filter(onThis).map((action) => ({ action, text: OUTCOME_UNKNOWN_TEXT })));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [kind, id]);

  useEffect(() => {
    if (usesAgent) void load();
  }, [usesAgent, load]);

  if (!usesAgent) return null;
  if (failed) return <p className="text-sm text-muted-foreground">Couldn&apos;t load the assistant&apos;s changes to this {RESOURCE_LABEL[kind]}.</p>;
  if (pending.length === 0 && lost.length === 0) return null;

  const drop = (actionId: string) => setPending((prev) => prev.filter((a) => a.action_id !== actionId));
  const fail = (actionId: string, text: string) => setErrors((prev) => ({ ...prev, [actionId]: text }));
  const loseAnswer = (action: AgentActionOut, text: string) => {
    drop(action.action_id);
    setLost((prev) => [{ action, text }, ...prev.filter((l) => l.action.action_id !== action.action_id)]);
  };

  const apply = async (action: AgentActionOut) => {
    const actionId = action.action_id;
    const change = changeOf(action);
    setBusy(actionId);
    fail(actionId, "");
    try {
      await (action.kind === "draft" ? agentApi.apply(action, edits[actionId] ?? payloadOf(action)) : agentApi.apply(action));
      drop(actionId);
      toast.success(`${change ? CHANGE_LABEL[change] : "The change"}: the cloud accepted it.`);
      onChanged();
    } catch (err) {
      if (!(err instanceof ApiError)) {
        try {
          const waiting = await agentApi.actions("state=pending");
          if (!waiting.some((a) => a.action_id === actionId)) {
            loseAnswer(action, "No answer came back, so it isn't known whether the change was sent. Check the resource before doing anything else.");
            return;
          }
        } catch {
          // the list is unreachable too: the action is shown as still waiting
        }
        fail(actionId, "Couldn't reach the server, and the change is still waiting. You can try again.");
        return;
      }
      const result = changeRefusal(err);
      if (result.kind === "unknown") {
        loseAnswer(action, result.text);
        onChanged();
      } else if (result.kind === "final") {
        drop(actionId);
        toast.info(result.text);
      } else {
        fail(actionId, result.text);
        if (err.code === "infra_state_changed") onChanged();
      }
    } finally {
      setBusy(null);
    }
  };

  const dismiss = async (action: AgentActionOut) => {
    setBusy(action.action_id);
    try {
      await agentApi.dismiss(action.action_id);
      drop(action.action_id);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) drop(action.action_id);
      else fail(action.action_id, "Couldn't dismiss it. Try again.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Panel title="Changes from the assistant">
      <div className="flex flex-col gap-3 text-sm">
        {lost.map(({ action, text }) => {
          const change = changeOf(action);
          return (
            <div key={action.action_id} role="status" className="flex items-start gap-2 rounded-md bg-warn-soft px-3 py-2.5 text-warn">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              <p>
                <span className="font-medium">{change ? CHANGE_LABEL[change] : "A change"}</span>, proposed {relativeTime(action.created_at)}: {text}{" "}
                <a href="#state" className="underline">
                  {name}&apos;s state
                </a>
              </p>
            </div>
          );
        })}
        {pending.map((action) => {
          const change = changeOf(action);
          const draft = action.kind === "draft";
          const body = edits[action.action_id] ?? payloadOf(action);
          const set = (field: string, value: unknown) => setEdits((prev) => ({ ...prev, [action.action_id]: { ...body, [field]: value } }));
          const removed = typeof body.rule_id === "string" ? rules.find((r) => r.id === body.rule_id) : undefined;
          return (
            <section
              key={action.action_id}
              aria-label={draft ? "Draft from the assistant" : "Change waiting for your confirmation"}
              className="flex flex-col gap-3 rounded-md border border-dashed border-proposal/50 bg-proposal-soft/40 px-4 py-3"
            >
              <p className="flex flex-wrap items-center gap-2 font-medium">
                <Bot className="size-4" aria-hidden />
                {draft ? "Draft from the assistant" : "Waiting for your confirmation"}: {change ? CHANGE_LABEL[change] : action.tool}
                <span className="font-normal text-muted-foreground">· {relativeTime(action.created_at)}</span>
              </p>
              {draft ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <Labeled label="Ticket" required hint="An open ticket you work on; the change is noted on it.">
                    <Input value={String(body.public_id ?? "")} maxLength={32} onChange={(e) => set("public_id", e.target.value)} />
                  </Labeled>
                  {change === "remove_security_rule" && (
                    <p className="self-end">
                      Removes <span className="font-mono text-xs">{String(body.rule_id ?? "")}</span>
                      {removed ? `: ${describeRule(removed)}` : " (not among this group's rules now)"}
                    </p>
                  )}
                  {change === "add_security_rule" && <RuleFields body={body as Partial<SecurityRuleIn>} set={set} />}
                </div>
              ) : (
                <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-1">
                  {typeof body.public_id === "string" && (
                    <>
                      <dt className="text-muted-foreground">Ticket</dt>
                      <dd>{body.public_id}</dd>
                    </>
                  )}
                  {typeof body.server_id === "string" && (
                    <>
                      <dt className="text-muted-foreground">To server</dt>
                      <dd className="font-mono text-xs">{body.server_id}</dd>
                    </>
                  )}
                </dl>
              )}
              <p className="text-xs text-muted-foreground">
                {draft
                  ? "The assistant can't make this change. Check the state on this page; applying it is your decision."
                  : "Nothing has been sent. Confirming sends exactly what the assistant proposed."}
              </p>
              {errors[action.action_id] && (
                <p role="alert" className="text-danger">
                  {errors[action.action_id]}
                </p>
              )}
              {!operates && <p className="text-xs text-muted-foreground">You can&apos;t change the cloud&apos;s resources, so only dismissing is open to you.</p>}
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" disabled={busy !== null || !operates} onClick={() => void apply(action)}>
                  {draft ? "Apply" : "Confirm"}
                </Button>
                <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => void dismiss(action)}>
                  Dismiss
                </Button>
              </div>
            </section>
          );
        })}
      </div>
    </Panel>
  );
}

function RuleFields({ body, set }: { body: Partial<SecurityRuleIn>; set: (field: string, value: unknown) => void }) {
  const port = (value: string) => (value.trim() === "" ? null : Number(value));
  return (
    <>
      <Labeled label="Direction">
        <NativeSelect value={body.direction ?? "ingress"} onChange={(e) => set("direction", e.target.value)}>
          <option value="ingress">ingress</option>
          <option value="egress">egress</option>
        </NativeSelect>
      </Labeled>
      <Labeled label="Ether type">
        <NativeSelect value={body.ethertype ?? "IPv4"} onChange={(e) => set("ethertype", e.target.value)}>
          <option value="IPv4">IPv4</option>
          <option value="IPv6">IPv6</option>
        </NativeSelect>
      </Labeled>
      <Labeled label="Protocol">
        <NativeSelect value={body.protocol ?? ""} onChange={(e) => set("protocol", e.target.value || null)}>
          <option value="">any</option>
          <option value="tcp">tcp</option>
          <option value="udp">udp</option>
          <option value="icmp">icmp</option>
        </NativeSelect>
      </Labeled>
      <Labeled label="Remote prefix" hint="Empty means anywhere.">
        <Input value={body.remote_ip_prefix ?? ""} onChange={(e) => set("remote_ip_prefix", e.target.value.trim() || null)} placeholder="10.10.0.0/24" />
      </Labeled>
      <Labeled label="From port">
        <Input type="number" min={1} max={65535} value={body.port_range_min ?? ""} onChange={(e) => set("port_range_min", port(e.target.value))} />
      </Labeled>
      <Labeled label="To port">
        <Input type="number" min={1} max={65535} value={body.port_range_max ?? ""} onChange={(e) => set("port_range_max", port(e.target.value))} />
      </Labeled>
    </>
  );
}
