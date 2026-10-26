"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, chatApi } from "./api";
import type { ChatTurnOut } from "./types/generated";

// How often a question still being analysed is checked. The pipeline runs
// in a Celery worker, so the answer arrives by polling, not in the response.
const POLL_MS = 1500;
// After this long, the thinking bubble says it is taking longer than usual.
// A cold model load alone takes 15-20s (docs: MODEL_TIMEOUT_SEC).
export const SLOW_AFTER_MS = 25_000;

/** One row of the conversation: a turn from core-api, or a question still
 * being submitted (masking runs inline, so that takes a moment too). */
export type Turn =
  | { kind: "sending"; key: string; text: string; startedAt: number }
  | { kind: "failed"; key: string; text: string; error: string }
  | { kind: "server"; key: string; turn: ChatTurnOut; startedAt: number };

/** The current chat conversation (F3): its turns, and the id each new question joins. */
export function useConversation(enabled: boolean) {
  const [turns, setTurns] = useState<Turn[]>([]);
  // The conversation the next question joins; null starts a new one.
  const conversationRef = useRef<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [creating, setCreating] = useState<string | null>(null);
  const [answering, setAnswering] = useState<string | null>(null);
  const turnsRef = useRef(turns);
  turnsRef.current = turns;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    chatApi
      .history()
      .then((history) => {
        if (cancelled) return;
        conversationRef.current = history.at(-1)?.conversation_id ?? null;
        setTurns(
          history.map((t) => ({
            kind: "server" as const,
            key: t.public_id,
            turn: t,
            startedAt: Date.parse(t.created_at),
          })),
        );
      })
      .catch(() => {
        // An empty conversation is still usable; asking will surface errors.
      })
      .finally(() => !cancelled && setLoaded(true));
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  const replace = useCallback((key: string, next: Turn) => {
    setTurns((prev) => prev.map((t) => (t.key === key ? next : t)));
  }, []);

  // Poll every turn that is still thinking, until each has an outcome.
  useEffect(() => {
    const thinking = turns.filter((t) => t.kind === "server" && t.turn.state === "thinking");
    if (thinking.length === 0) return;
    const timer = window.setTimeout(async () => {
      for (const t of thinking) {
        if (t.kind !== "server") continue;
        try {
          const fresh = await chatApi.turn(t.turn.public_id);
          if (fresh.state !== t.turn.state) replace(t.key, { ...t, turn: fresh });
        } catch {
          // transient: the next tick tries again
        }
      }
      // Re-arm even when nothing changed, by nudging state identity.
      setTurns((prev) => [...prev]);
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [turns, replace]);

  /** Sends a new question; returns at once the key its turn is shown under. */
  const ask = useCallback(
    (text: string): string => {
      const key = `local-${Date.now()}`;
      const startedAt = Date.now();
      setTurns((prev) => [...prev, { kind: "sending", key, text, startedAt }]);
      const send = () => chatApi.ask(text, conversationRef.current);
      void send()
        .catch((err) => {
          // Idle for too long, or ended elsewhere: the question starts a new conversation.
          if (!(err instanceof ApiError && err.code === "conversation_ended")) throw err;
          conversationRef.current = null;
          setTurns((prev) => prev.filter((t) => t.key === key));
          return send();
        })
        .then((turn) => {
          conversationRef.current = turn.conversation_id ?? null;
          replace(key, { kind: "server", key, turn, startedAt });
        })
        .catch((err) => {
          const error =
            err instanceof ApiError && err.status === 422
              ? "Please describe the problem in at least 10 characters."
              : "I couldn't send that. Check your connection and try again.";
          replace(key, { kind: "failed", key, text, error });
        });
      return key;
    },
    [replace],
  );

  // Puts a fresh copy of the turn for `publicId` in place.
  const refresh = useCallback(
    (publicId: string, fresh: ChatTurnOut, startedAt?: number) => {
      const t = turnsRef.current.find((x) => x.kind === "server" && x.turn.public_id === publicId);
      if (t && t.kind === "server") replace(t.key, { ...t, turn: fresh, startedAt: startedAt ?? t.startedAt });
    },
    [replace],
  );

  // A POST on one turn. A 409 means it already moved on (with support, or
  // the question closed), so the turn is reloaded to show where it is.
  const act = useCallback(
    async (publicId: string, call: () => Promise<ChatTurnOut>, setBusy: (id: string | null) => void, restart = false) => {
      setBusy(publicId);
      try {
        refresh(publicId, await call(), restart ? Date.now() : undefined);
      } catch {
        const fresh = await chatApi.turn(publicId).catch(() => null);
        if (fresh) refresh(publicId, fresh);
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  const createTicket = useCallback(
    (publicId: string) => act(publicId, () => chatApi.createTicket(publicId), setCreating),
    [act],
  );

  // The requester's answer to a clarifying question. The ticket goes back to
  // "thinking" while the pipeline runs again, so polling picks it up.
  const answer = useCallback(
    (publicId: string, text: string) => act(publicId, () => chatApi.clarify(publicId, text), setAnswering, true),
    [act],
  );

  /** Sends a failed question again; returns the key of its new turn. */
  const retry = useCallback(
    (key: string): string | null => {
      const t = turnsRef.current.find((x) => x.key === key);
      if (!t || t.kind !== "failed") return null;
      setTurns((prev) => prev.filter((x) => x.key !== key));
      return ask(t.text);
    },
    [ask],
  );

  /** Ends the conversation on screen ("Cuộc trò chuyện mới"): the next question has no context. */
  const startNew = useCallback(async () => {
    const current = conversationRef.current;
    conversationRef.current = null;
    setTurns([]);
    if (current) await chatApi.endConversation(current).catch(() => undefined);
  }, []);

  const startedAt = turns.find((t) => t.kind === "server")?.startedAt ?? null;

  return { turns, loaded, ask, createTicket, creating, answer, answering, retry, startNew, startedAt };
}
