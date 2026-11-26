"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { agentApi, ApiError, chatApi, infraApi } from "./api";
import { CHANGE_REFUSAL, changeDone, OUTCOME_UNKNOWN_TEXT } from "./infra";
import type {
  AgentActionOut,
  AgentChoiceOut,
  AgentConversationSummaryOut,
  AgentTurnOut,
  ChatTurnOut,
  InfraChangeOut,
  ResourceKind,
} from "./types/generated";

// Mirror AgentTurnIn.message in core-api (apps/agent/request_schema.py).
export const AGENT_MESSAGE_MIN = 1;
export const AGENT_MESSAGE_MAX = 4_000;

// How often an unfinished turn, and a hand-off ticket still being triaged, is checked.
const POLL_MS = 1500;

/** One row of the assistant conversation: a turn from core-api, or a message still being sent. */
export type AgentRow =
  | { kind: "ended"; key: string }
  | { kind: "sending"; key: string; text: string }
  | { kind: "failed"; key: string; text: string; error: string }
  | { kind: "server"; key: string; turn: AgentTurnOut };

const UNFINISHED = new Set(["queued", "running"]);

// The choice kinds that name a cloud resource, which a press also records as a pick (F17 BR-F17-26).
const RESOURCE_KINDS: ReadonlySet<string> = new Set<ResourceKind>(["server", "volume", "network"]);

function namesAResource(kind: string): kind is ResourceKind {
  return RESOURCE_KINDS.has(kind);
}

/** What became of a confirmation the employee answered, shown in place of its card. */
export type ActionResult = { label: string; tone: "ok" | "info" | "warn"; text: string; ticket?: string };

// Refusals after which the action is no longer pending: its card gives way to the message.
const FINAL_REFUSALS: Record<string, string> = {
  agent_action_expired: "This has expired. Ask the assistant again if you still want it.",
  agent_action_not_pending: "This can no longer be sent. Ask the assistant again if you still want it.",
  not_pending: "This can no longer be sent. Ask the assistant again if you still want it.",
  infra_outcome_unknown: OUTCOME_UNKNOWN_TEXT,
};

function confirmedResult(action: AgentActionOut, response: unknown): ActionResult {
  if (action.target_kind === "server") {
    const change = response as InfraChangeOut | null;
    const done = change?.change ? changeDone(change.change, change.target_name) : null;
    return { label: "Done", tone: "ok", text: done ?? "Sent." };
  }
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

function lostTurnError(err: ApiError): string {
  if (err.status === 401) return "Your sign-in ended. Sign in again to keep talking to the assistant.";
  return "I lost track of that message. You can send it again.";
}

function sendError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "agent_off") return "The assistant is switched off right now. Ask someone on the support team.";
    if (err.code === "turn_running") return "The assistant is still working on your last message.";
    if (err.status === 422) return `Please type a message of up to ${AGENT_MESSAGE_MAX.toLocaleString()} characters.`;
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
  const [history, setHistory] = useState<AgentConversationSummaryOut[]>([]);
  const [historyError, setHistoryError] = useState(false);
  // An ended conversation opened from the history: it can be read, not added to.
  const [viewingEnded, setViewingEnded] = useState(false);
  const resumed = useRef(false);
  // Counts finished polls.
  const [turnTick, setTurnTick] = useState(0);
  const [handoffTick, setHandoffTick] = useState(0);
  const handoffTried = useRef(new Set<string>());
  // Confirmations a finished turn named that the pending list has been asked about.
  const pendingChecked = useRef(new Set<string>());
  const [pendingTick, setPendingTick] = useState(0);
  const [pendingError, setPendingError] = useState(false);
  const polling = useRef(false);
  const conversationRef = useRef<string | null>(null);
  const busy = rows.some((r) => r.kind === "sending" || (r.kind === "server" && UNFINISHED.has(r.turn.state)));
  // Whether a message may be sent now: not while a turn runs, nor in an ended conversation.
  const blocked = useRef(false);
  useEffect(() => {
    blocked.current = busy || viewingEnded;
  }, [busy, viewingEnded]);

  const loadHistory = useCallback(
    () =>
      agentApi
        .conversations()
        .then((list) => {
          setHistoryError(false);
          setHistory(list);
          return list;
        })
        .catch(() => {
          setHistoryError(true);
          return [] as AgentConversationSummaryOut[];
        }),
    [],
  );

  /** Shows a conversation from the history; an active one is continued, an ended one is read-only. */
  const open = useCallback(async (id: string) => {
    try {
      const conversation = await agentApi.conversation(id);
      const active = conversation.state === "active";
      conversationRef.current = active ? id : null;
      setViewingEnded(!active);
      setRows(conversation.turns.map((t) => ({ kind: "server" as const, key: t.turn_id, turn: t })));
    } catch {
      setHistoryError(true);
    }
  }, []);

  // The latest conversation, if it is still active, is where the person left it.
  useEffect(() => {
    if (!enabled || resumed.current) return;
    resumed.current = true;
    void loadHistory().then((list) => {
      if (list[0]?.state === "active") void open(list[0].conversation_id);
    });
  }, [enabled, loadHistory, open]);

  const replace = useCallback((key: string, next: AgentRow) => {
    setRows((prev) => prev.map((r) => (r.key === key ? next : r)));
  }, []);

  const loadPending = useCallback(() => {
    agentApi
      .pending()
      .then(setPending)
      .catch(() => undefined);
  }, []);

  // A finished turn can have asked for a confirmation whichever way it stopped; load the cards it
  // names until each is either listed or known not to be.
  useEffect(() => {
    if (!enabled) return;
    const listed = new Set(pending.map((a) => a.action_id));
    const missing = rows.flatMap((r) =>
      r.kind === "server" && !UNFINISHED.has(r.turn.state)
        ? r.turn.receipts.flatMap((x) =>
            x.outcome === "awaiting_confirmation" && x.action_id && !listed.has(x.action_id) && !results[x.action_id]
              ? [x.action_id]
              : [],
          )
        : [],
    ).filter((id) => !pendingChecked.current.has(id));
    if (missing.length === 0) return;
    const timer = window.setTimeout(
      () => {
        agentApi
          .pending()
          .then((list) => {
            missing.forEach((id) => pendingChecked.current.add(id));
            setPendingError(false);
            setPending(list);
          })
          .catch(() => {
            setPendingError(true);
            setPendingTick((n) => n + 1);
          });
      },
      pendingTick === 0 ? 0 : POLL_MS,
    );
    return () => window.clearTimeout(timer);
  }, [enabled, rows, pending, results, pendingTick]);

  // Poll each unfinished turn until it has an outcome.
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
          }
        } catch (err) {
          if (err instanceof ApiError && [401, 403, 404].includes(err.status)) {
            replace(r.key, { kind: "failed", key: r.key, text: r.turn.message_masked, error: lostTurnError(err) });
          }
        }
      }
      polling.current = false;
      setTurnTick((n) => n + 1);
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [enabled, rows, replace, turnTick]);

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

  /** Sends a message, unless a turn is running or an ended conversation is on screen; a
   * conversation that ended on the server is replaced by a new one. Resolves to the turn that
   * took it, or null when it wasn't sent. */
  const send = useCallback(
    (text: string): Promise<AgentTurnOut | null> => {
      if (blocked.current) return Promise.resolve(null);
      blocked.current = true;
      const key = `local-${Date.now()}`;
      setRows((prev) => [...prev, { kind: "sending", key, text }]);
      const post = () => agentApi.send(text, conversationRef.current);
      return post()
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
          void loadHistory();
          return turn;
        })
        .catch((err) => {
          replace(key, { kind: "failed", key, text, error: sendError(err) });
          return null;
        });
    },
    [replace, loadHistory],
  );

  /** Sends a pressed choice's label as the next message; once it is sent, a server, volume or
   * network is also posted as the person's pick, on the conversation that took the message. */
  const choose = useCallback(
    (choice: AgentChoiceOut) => {
      const { kind, id } = choice;
      void send(choice.label).then((turn) => {
        if (turn && id && namesAResource(kind)) {
          void infraApi
            .pick({ conversation_id: turn.conversation_id, kind, resource_id: id })
            .catch(() => undefined);
        }
      });
    },
    [send],
  );

  const retry = useCallback(
    (key: string) => {
      const row = rows.find((r) => r.key === key);
      if (!row || row.kind !== "failed" || blocked.current) return;
      setRows((prev) => prev.filter((r) => r.key !== key));
      void send(row.text);
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
        const code = err instanceof ApiError ? err.code : null;
        let final = code ? FINAL_REFUSALS[code] : undefined;
        let label = code === "infra_outcome_unknown" ? "Not sure" : "Not sent";
        if (!(err instanceof ApiError) || (err.status >= 500 && !code)) {
          // No answer came back: the server's own list says whether the action is still waiting.
          try {
            const list = await agentApi.pending();
            setPending(list);
            if (!list.some((a) => a.action_id === id)) {
              label = "Not sure";
              final = !run
                ? "I couldn't tell whether that was cancelled. It is no longer waiting for you."
                : action.target_kind === "server"
                  ? OUTCOME_UNKNOWN_TEXT
                  : "I couldn't tell whether that went through. Check your ticket before trying again.";
            }
          } catch {
            // the list is unreachable too: the card stays, with a retry
          }
          if (!final) {
            setActionError((prev) => ({ ...prev, [id]: "I couldn't reach the server. Try again." }));
            return;
          }
        }
        if (final) {
          setResults((prev) => ({ ...prev, [id]: { label, tone: "warn", text: final } }));
          setPending((prev) => prev.filter((a) => a.action_id !== id));
        } else {
          setActionError((prev) => ({
            ...prev,
            [id]: err instanceof ApiError ? (code && CHANGE_REFUSAL[code]) || err.message : "That didn't go through. Try again.",
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
      const fresh = await chatApi.createTicket(publicId).catch((err) => {
        if (err instanceof ApiError && err.status === 409) return chatApi.turn(publicId);
        throw err;
      });
      setHandoffs((prev) => ({ ...prev, [fresh.public_id]: fresh }));
      if (fresh.state === "suggest_ticket") throw new Error("still waiting");
    } catch {
      setCreateError((prev) => ({ ...prev, [publicId]: "I couldn't open the ticket. Try again." }));
    } finally {
      setCreating(null);
    }
  }, []);

  /** Opens the ticket a handed-off turn offers, and shows the turn with it. */
  const openTicket = useCallback(async (turnId: string) => {
    setCreating(turnId);
    setCreateError((prev) => ({ ...prev, [turnId]: "" }));
    try {
      const fresh = await agentApi.openTicket(turnId);
      setRows((prev) =>
        prev.map((r) => (r.kind === "server" && r.turn.turn_id === turnId ? { ...r, turn: fresh } : r)),
      );
    } catch {
      setCreateError((prev) => ({ ...prev, [turnId]: "I couldn't open the ticket. Try again." }));
    } finally {
      setCreating(null);
    }
  }, []);

  /** Ends the conversation on screen: the next message starts a new one. */
  const startNew = useCallback(async () => {
    const current = conversationRef.current;
    conversationRef.current = null;
    setRows([]);
    setViewingEnded(false);
    if (current) await agentApi.endConversation(current).catch(() => undefined);
    void loadHistory();
  }, [loadHistory]);

  return {
    rows,
    pending,
    handoffs,
    busyAction,
    actionError,
    results,
    creating,
    createError,
    pendingError,
    history,
    historyError,
    viewingEnded,
    open,
    send,
    choose,
    retry,
    confirm: (a: AgentActionOut) => resolve(a, true),
    dismiss: (a: AgentActionOut) => resolve(a, false),
    createTicket,
    openTicket,
    startNew,
    busy,
  };
}
