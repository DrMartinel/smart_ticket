"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { agentApi, ApiError, chatApi } from "./api";
import type { AgentActionOut, AgentTurnOut, ChatTurnOut } from "./types/generated";

// How often an unfinished turn, and a hand-off ticket still being triaged, is checked.
const POLL_MS = 1500;

/** One row of the assistant conversation: a turn from core-api, or a message still being sent. */
export type AgentRow =
  | { kind: "ended"; key: string }
  | { kind: "sending"; key: string; text: string }
  | { kind: "failed"; key: string; text: string; error: string }
  | { kind: "server"; key: string; turn: AgentTurnOut };

const UNFINISHED = new Set(["queued", "running"]);

/** What became of a confirmation the employee answered, shown in place of its card. */
export type ActionResult = { label: string; tone: "ok" | "info" | "warn"; text: string; ticket?: string };

// Refusals after which the action is no longer pending: its card gives way to the message.
const FINAL_REFUSALS: Record<string, string> = {
  agent_action_expired: "This has expired. Ask the assistant again if you still want it.",
  agent_action_not_pending: "This was already dealt with.",
  not_pending: "This was already dealt with.",
};

function confirmedResult(action: AgentActionOut, response: unknown): ActionResult {
  const reopen = response as { reopened?: boolean; new_ticket?: string | null } | null;
  if (reopen && reopen.reopened === false && reopen.new_ticket) {
    return {
      label: "Done",
      tone: "ok",
      text: "That ticket was closed too long ago to reopen, so a new one was opened:",
      ticket: reopen.new_ticket,
    };
  }
  return { label: "Done", tone: "ok", text: action.tool === "reopen_my_ticket" ? "Reopened." : "Sent." };
}

function sendError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "agent_off") return "The assistant is switched off right now. You can still ask on the Ask page.";
    if (err.code === "turn_running") return "The assistant is still working on your last message.";
    if (err.status === 422) return err.message;
  }
  return "I couldn't send that. Check your connection and try again.";
}

/** The assistant conversation on screen: its turns, the confirmations waiting, and hand-off tickets. */
export function useAgentConversation(enabled: boolean) {
  const [rows, setRows] = useState<AgentRow[]>([]);
  const [pending, setPending] = useState<AgentActionOut[]>([]);
  // The chat ticket each hand-off opened, by public id.
  const [handoffs, setHandoffs] = useState<Record<string, ChatTurnOut>>({});
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState<Record<string, string>>({});
  const [results, setResults] = useState<Record<string, ActionResult>>({});
  const [creating, setCreating] = useState<string | null>(null);
  const [createError, setCreateError] = useState<Record<string, string>>({});
  // Bumped after each poll, so the next one is scheduled whether or not anything changed.
  const [turnTick, setTurnTick] = useState(0);
  const [handoffTick, setHandoffTick] = useState(0);
  const handoffTried = useRef(new Set<string>());
  const conversationRef = useRef<string | null>(null);

  const replace = useCallback((key: string, next: AgentRow) => {
    setRows((prev) => prev.map((r) => (r.key === key ? next : r)));
  }, []);

  const loadPending = useCallback(() => {
    agentApi
      .pending()
      .then(setPending)
      .catch(() => undefined);
  }, []);

  // Poll each unfinished turn until it has an outcome.
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
      setTurnTick((n) => n + 1);
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [enabled, rows, replace, loadPending, turnTick]);

  // Load each hand-off ticket, and poll it while the helpdesk is still deciding.
  useEffect(() => {
    const ids = rows.flatMap((r) => (r.kind === "server" && r.turn.handoff_ticket ? [r.turn.handoff_ticket] : []));
    const due = ids.filter((id) => !handoffs[id] || handoffs[id].state === "thinking");
    if (due.length === 0) return;
    const first = due.some((id) => !handoffTried.current.has(id));
    const timer = window.setTimeout(
      async () => {
        due.forEach((id) => handoffTried.current.add(id));
        const fresh = (await Promise.all(due.map((id) => chatApi.turn(id).catch(() => null)))).filter(
          (t): t is ChatTurnOut => t !== null,
        );
        if (fresh.length > 0) {
          setHandoffs((prev) => {
            const next = { ...prev };
            fresh.forEach((t) => (next[t.public_id] = t));
            return next;
          });
        }
        setHandoffTick((n) => n + 1);
      },
      first ? 0 : POLL_MS,
    );
    return () => window.clearTimeout(timer);
  }, [rows, handoffs, handoffTick]);

  /** Sends a message; a conversation that has ended is replaced by a new one. */
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

  /** Runs or cancels a confirmation; once it is no longer pending, its result replaces the card. */
  const resolve = useCallback(
    async (action: AgentActionOut, run: boolean) => {
      const id = action.action_id;
      setBusyAction(id);
      setActionError((prev) => ({ ...prev, [id]: "" }));
      try {
        const response = await (run ? agentApi.confirm(action) : agentApi.dismiss(id));
        setResults((prev) => ({
          ...prev,
          [id]: run ? confirmedResult(action, response) : { label: "Cancelled", tone: "info", text: "Nothing was sent." },
        }));
        setPending((prev) => prev.filter((a) => a.action_id !== id));
      } catch (err) {
        const final = err instanceof ApiError && err.code ? FINAL_REFUSALS[err.code] : undefined;
        if (final) {
          setResults((prev) => ({ ...prev, [id]: { label: "Not sent", tone: "warn", text: final } }));
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

  const createTicket = useCallback(async (publicId: string) => {
    setCreating(publicId);
    setCreateError((prev) => ({ ...prev, [publicId]: "" }));
    try {
      const fresh = await chatApi.createTicket(publicId).catch(() => chatApi.turn(publicId));
      setHandoffs((prev) => ({ ...prev, [fresh.public_id]: fresh }));
    } catch {
      setCreateError((prev) => ({ ...prev, [publicId]: "I couldn't open the ticket. Try again." }));
    } finally {
      setCreating(null);
    }
  }, []);

  /** Ends the conversation on screen: the next message starts a new one. */
  const startNew = useCallback(async () => {
    const current = conversationRef.current;
    conversationRef.current = null;
    setRows([]);
    if (current) await agentApi.endConversation(current).catch(() => undefined);
  }, []);

  return {
    rows,
    pending,
    handoffs,
    busyAction,
    actionError,
    results,
    creating,
    createError,
    send,
    retry,
    confirm: (a: AgentActionOut) => resolve(a, true),
    dismiss: (a: AgentActionOut) => resolve(a, false),
    createTicket,
    startNew,
    busy: rows.some((r) => r.kind === "sending" || (r.kind === "server" && UNFINISHED.has(r.turn.state))),
  };
}
