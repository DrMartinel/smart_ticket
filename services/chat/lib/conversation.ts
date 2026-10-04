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

export function useConversation(enabled: boolean) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [creating, setCreating] = useState<string | null>(null);
  const turnsRef = useRef(turns);
  turnsRef.current = turns;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    chatApi
      .history()
      .then((history) => {
        if (cancelled) return;
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

  const ask = useCallback(
    async (text: string) => {
      const key = `local-${Date.now()}`;
      const startedAt = Date.now();
      setTurns((prev) => [...prev, { kind: "sending", key, text, startedAt }]);
      try {
        const turn = await chatApi.ask(text);
        replace(key, { kind: "server", key, turn, startedAt });
      } catch (err) {
        const error =
          err instanceof ApiError && err.status === 422
            ? "Please describe the problem in at least 10 characters."
            : "I couldn't send that. Check your connection and try again.";
        replace(key, { kind: "failed", key, text, error });
      }
    },
    [replace],
  );

  const createTicket = useCallback(
    async (publicId: string) => {
      setCreating(publicId);
      try {
        const fresh = await chatApi.createTicket(publicId);
        const t = turnsRef.current.find((x) => x.kind === "server" && x.turn.public_id === publicId);
        if (t && t.kind === "server") replace(t.key, { ...t, turn: fresh });
      } catch {
        // 409: already with support. Reload that turn to show where it is.
        const fresh = await chatApi.turn(publicId).catch(() => null);
        const t = turnsRef.current.find((x) => x.kind === "server" && x.turn.public_id === publicId);
        if (fresh && t && t.kind === "server") replace(t.key, { ...t, turn: fresh });
      } finally {
        setCreating(null);
      }
    },
    [replace],
  );

  const retry = useCallback(
    (key: string) => {
      const t = turnsRef.current.find((x) => x.key === key);
      if (!t || t.kind !== "failed") return;
      setTurns((prev) => prev.filter((x) => x.key !== key));
      void ask(t.text);
    },
    [ask],
  );

  return { turns, loaded, ask, createTicket, creating, retry };
}
