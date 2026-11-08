"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { AgentActionOut, AgentTurnOut } from "./types/generated";

// How often an unfinished turn is checked.
const POLL_MS = 1500;
const UNFINISHED = new Set(["queued", "running"]);

/** The header that applies an assistant's action with the person's own session (ADR-0046 §7–8). */
export const AGENT_ACTION_HEADER = "X-Agent-Action";

/** What each console tool is called on a receipt, a card or a draft banner. */
export const TOOL_LABEL: Record<string, string> = {
  take_ticket: "Take the ticket",
  add_comment: "Add a comment",
  claim_review_item: "Claim the review",
  draft_review_decision: "Review decision",
  draft_comment_decision: "Comment decision",
  draft_reassign: "Reassign",
  draft_priority: "Change priority",
};

export const agentApi = {
  send: (message: string, conversationId: string | null) =>
    api.post<AgentTurnOut>("/api/agent/turns", {
      message,
      surface: "console",
      ...(conversationId ? { conversation_id: conversationId } : {}),
    }),
  turn: (id: string) => api.get<AgentTurnOut>(`/api/agent/turns/${encodeURIComponent(id)}`),
  endConversation: (id: string) => api.post<void>(`/api/agent/conversations/${encodeURIComponent(id)}/end`),
  actions: (query: string) => api.get<AgentActionOut[]>(`/api/agent/actions?${query}`),
  dismiss: (id: string) => api.post<void>(`/api/agent/actions/${encodeURIComponent(id)}/dismiss`),
  /** Sends `body` (the stored payload unless edited) to the action's route with the person's session. */
  apply: <T>(action: AgentActionOut, body: unknown = action.arguments.payload) =>
    api.call<T>(action.method, action.path, body, { [AGENT_ACTION_HEADER]: action.action_id }),
};

export type AgentRow =
  | { kind: "ended"; key: string }
  | { kind: "sending"; key: string; text: string }
  | { kind: "failed"; key: string; text: string; error: string }
  | { kind: "server"; key: string; turn: AgentTurnOut };

/** What became of a confirmation the person answered, shown in place of its card. */
export type ActionResult = { label: string; tone: "ok" | "info" | "warn"; text: string };

// Mirror AgentTurnIn.message in core-api (apps/agent/request_schema.py).
export const AGENT_MESSAGE_MAX = 4_000;

// Refusals after which the action is no longer pending: its card gives way to the message.
const FINAL_REFUSALS: Record<string, string> = {
  agent_action_expired: "This has expired. Ask the assistant again if you still want it.",
  agent_action_not_pending: "This can no longer be applied. Ask the assistant again if you still want it.",
  not_pending: "This can no longer be applied. Ask the assistant again if you still want it.",
};

function sendError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "agent_off") return "The assistant is switched off.";
    if (err.code === "turn_running") return "The assistant is still working on your last message.";
    if (err.code === "permission_missing") return "The assistant needs ticket access you don't have.";
    if (err.status === 422) return `Messages are up to ${AGENT_MESSAGE_MAX.toLocaleString()} characters.`;
  }
  return "Couldn't send that. Try again.";
}

/** The console assistant's conversation: its turns and the confirmations waiting on them. */
export function useAgentConversation(enabled: boolean) {
  const [rows, setRows] = useState<AgentRow[]>([]);
  const [pending, setPending] = useState<AgentActionOut[]>([]);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState<Record<string, string>>({});
  const [results, setResults] = useState<Record<string, ActionResult>>({});
  // Counts finished polls.
  const [tick, setTick] = useState(0);
  const polling = useRef(false);
  const conversationRef = useRef<string | null>(null);

  const replace = useCallback((key: string, next: AgentRow) => {
    setRows((prev) => prev.map((r) => (r.key === key ? next : r)));
  }, []);

  const loadPending = useCallback(() => {
    agentApi
      .actions("state=pending&kind=confirm")
      .then(setPending)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const waiting = rows.filter((r) => r.kind === "server" && UNFINISHED.has(r.turn.state));
    if (waiting.length === 0) return;
    const timer = window.setTimeout(async () => {
      if (polling.current) return;
      polling.current = true;
      for (const r of waiting) {
        if (r.kind !== "server") continue;
        try {
          const fresh = await agentApi.turn(r.turn.turn_id);
          if (fresh.state !== r.turn.state) {
            replace(r.key, { ...r, turn: fresh });
            if (fresh.state === "awaiting_confirmation") loadPending();
          }
        } catch {
          // the next tick tries again
        }
      }
      polling.current = false;
      setTick((n) => n + 1);
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [enabled, rows, replace, loadPending, tick]);

  const send = useCallback(
    (text: string) => {
      const key = `local-${Date.now()}`;
      setRows((prev) => [...prev, { kind: "sending", key, text }]);
      const post = () => agentApi.send(text, conversationRef.current);
      void post()
        .catch((err) => {
          if (!(err instanceof ApiError && err.code === "conversation_ended")) throw err;
          conversationRef.current = null;
          setRows((prev) => {
            const earlier = prev.filter((r) => r.key !== key);
            const mine = prev.filter((r) => r.key === key);
            return earlier.length > 0 ? [...earlier, { kind: "ended", key: `ended-${key}` }, ...mine] : mine;
          });
          return post();
        })
        .then((turn) => {
          conversationRef.current = turn.conversation_id;
          replace(key, { kind: "server", key, turn });
        })
        .catch((err) => replace(key, { kind: "failed", key, text, error: sendError(err) }));
    },
    [replace],
  );

  const retry = useCallback(
    (key: string) => {
      const row = rows.find((r) => r.key === key);
      if (!row || row.kind !== "failed") return;
      setRows((prev) => prev.filter((r) => r.key !== key));
      send(row.text);
    },
    [rows, send],
  );

  /** Applies or cancels a confirmation; once it is no longer pending, its result replaces the card. */
  const resolve = useCallback(
    async (action: AgentActionOut, run: boolean) => {
      const id = action.action_id;
      setBusyAction(id);
      setActionError((prev) => ({ ...prev, [id]: "" }));
      try {
        await (run ? agentApi.apply(action) : agentApi.dismiss(id));
        setResults((prev) => ({
          ...prev,
          [id]: run
            ? { label: "Done", tone: "ok", text: "Applied." }
            : { label: "Cancelled", tone: "info", text: "Nothing was applied." },
        }));
        setPending((prev) => prev.filter((a) => a.action_id !== id));
      } catch (err) {
        const final =
          err instanceof ApiError
            ? err.code
              ? FINAL_REFUSALS[err.code]
              : undefined
            : "Couldn't tell whether that was applied. Check the ticket before trying again.";
        if (final) {
          const label = err instanceof ApiError ? "Not applied" : "Not sure";
          setResults((prev) => ({ ...prev, [id]: { label, tone: "warn", text: final } }));
          setPending((prev) => prev.filter((a) => a.action_id !== id));
        } else {
          setActionError((prev) => ({
            ...prev,
            [id]: err instanceof ApiError ? err.message : "That didn't go through. Try again.",
          }));
          loadPending();
        }
      } finally {
        setBusyAction(null);
      }
    },
    [loadPending],
  );

  const startNew = useCallback(async () => {
    const current = conversationRef.current;
    conversationRef.current = null;
    setRows([]);
    if (current) await agentApi.endConversation(current).catch(() => undefined);
  }, []);

  return {
    rows,
    pending,
    busyAction,
    actionError,
    results,
    send,
    retry,
    confirm: (a: AgentActionOut) => resolve(a, true),
    dismiss: (a: AgentActionOut) => resolve(a, false),
    startNew,
    busy: rows.some((r) => r.kind === "sending" || (r.kind === "server" && UNFINISHED.has(r.turn.state))),
  };
}
