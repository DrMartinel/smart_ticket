"use client";

// The helpdesk's own answer to a question the assistant asked for the employee: the
// approved page's text with its source, or the clarify choices, or the offer of a ticket.

import { useCallback, useEffect, useState } from "react";
import { chatApi } from "@/lib/api";
import type { ChatTurnOut } from "@/lib/types/generated";
import { ClarifyCard, Outcome } from "./TurnView";

// How often an answer still being analysed is checked.
const POLL_MS = 1500;

export default function HelpdeskCard({ publicId, onAnswer }: { publicId: string; onAnswer: (text: string) => void }) {
  const [turn, setTurn] = useState<ChatTurnOut | null>(null);
  const [creating, setCreating] = useState(false);
  const [startedAt] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const load = () =>
      chatApi
        .turn(publicId)
        .then((fresh) => {
          if (cancelled) return;
          setTurn(fresh);
          if (fresh.state === "thinking") timer = window.setTimeout(load, POLL_MS);
        })
        .catch(() => undefined);
    void load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [publicId]);

  const createTicket = useCallback(async () => {
    setCreating(true);
    try {
      setTurn(await chatApi.createTicket(publicId));
    } catch {
      setTurn(await chatApi.turn(publicId).catch(() => null));
    } finally {
      setCreating(false);
    }
  }, [publicId]);

  if (!turn) return null;
  return (
    <div className="border-t border-border pt-3">
      {turn.state === "clarify" && turn.clarification ? (
        <ClarifyCard
          clarification={turn.clarification}
          onAnswer={onAnswer}
          answering={false}
          onCreateTicket={() => void createTicket()}
          creating={creating}
        />
      ) : (
        <Outcome turn={turn} startedAt={startedAt} onCreateTicket={() => void createTicket()} creating={creating} />
      )}
    </div>
  );
}
