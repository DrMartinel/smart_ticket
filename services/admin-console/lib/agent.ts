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
  | { kind: "sending"; key: string; text: string }
  | { kind: "failed"; key: string; text: string; error: string }
  | { kind: "server"; key: string; turn: AgentTurnOut };

function sendError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "agent_off") return "The assistant is switched off.";
    if (err.code === "turn_running") return "The assistant is still working on your last message.";
    if (err.code === "permission_missing") return "The assistant needs ticket access you don't have.";
    if (err.status === 422) return "Messages are up to 4,000 characters.";
  }
  return "Couldn't send that. Try again.";
}

/** The console assistant's conversation: its turns and the confirmations waiting on them. */
export function useAgentConversation(enabled: boolean) {
  const [rows, setRows] = useState<AgentRow[]>([]);
  const [pending, setPending] = useState<AgentActionOut[]>([]);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState<Record<string, string>>({});
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
      for (const r of waiting) {
        if (r.kind !== "server") continue;
        try {
          const fresh = await agentApi.turn(r.turn.turn_id);
          if (fresh.state !== r.turn.state) {
            replace(r.key, { ...r, turn: fresh });
            if (fresh.state === "awaiting_confirmation") loadPending();
          }
        } catch {
          // transient: the next tick tries again
        }
      }
      setRows((prev) => [...prev]);
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [enabled, rows, replace, loadPending]);

  const send = useCallback(
    (text: string) => {
      const key = `local-${Date.now()}`;
      setRows((prev) => [...prev, { kind: "sending", key, text }]);
      const post = () => agentApi.send(text, conversationRef.current);
      void post()
        .catch((err) => {
          if (!(err instanceof ApiError && err.code === "conversation_ended")) throw err;
          conversationRef.current = null;
          setRows((prev) => prev.filter((r) => r.key === key));
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

  const resolve = useCallback(
    async (action: AgentActionOut, run: boolean) => {
      setBusyAction(action.action_id);
      setActionError((prev) => ({ ...prev, [action.action_id]: "" }));
      try {
        await (run ? agentApi.apply(action) : agentApi.dismiss(action.action_id));
        setPending((prev) => prev.filter((a) => a.action_id !== action.action_id));
      } catch (err) {
        setActionError((prev) => ({
          ...prev,
          [action.action_id]: err instanceof ApiError ? err.message : "That didn't go through. Try again.",
        }));
        loadPending();
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
    send,
    confirm: (a: AgentActionOut) => resolve(a, true),
    dismiss: (a: AgentActionOut) => resolve(a, false),
    startNew,
    busy: rows.some((r) => r.kind === "sending" || (r.kind === "server" && UNFINISHED.has(r.turn.state))),
  };
}
