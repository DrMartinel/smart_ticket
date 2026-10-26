"use client";

// The chat: one conversation at a time (F3 FR-F3-004). Each question becomes a ticket; the
// assistant sees the conversation's earlier masked turns, and older ones live in My tickets.

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useConversation } from "@/lib/conversation";
import AppHeader from "@/components/AppHeader";
import Composer from "@/components/Composer";
import TurnView from "@/components/TurnView";
import Welcome from "@/components/Welcome";

export default function ChatPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const { turns, ask, createTicket, creating, answer, answering, retry, startNew, startedAt } =
    useConversation(!!user);
  const endRef = useRef<HTMLDivElement>(null);
  const last = turns.at(-1);
  const lastState = last?.kind === "server" ? last.turn.state : last?.kind;

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, lastState]);

  if (!user) return null;

  const busy = turns.some((t) => t.kind === "sending");

  return (
    <div className="flex h-dvh flex-col">
      <AppHeader />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6 md:px-6">
          {turns.length > 0 && (
            <p className="flex flex-wrap items-center justify-between gap-2 rounded-[5px] bg-[var(--accent-soft)] px-3 py-2 text-xs text-[var(--accent)]">
              <span>
                {startedAt ? `Cuộc trò chuyện từ ${clock(startedAt)} · ` : ""}the assistant remembers the last 6 turns of
                this conversation · ends after 30 min idle
              </span>
              <button onClick={() => void startNew()} disabled={busy} className="font-medium hover:underline">
                + Cuộc trò chuyện mới · New conversation
              </button>
            </p>
          )}
          {turns.length === 0 ? (
            <Welcome name={user.username} onPick={ask} />
          ) : (
            turns.map((t) => (
              <TurnView
                key={t.key}
                turn={t}
                onCreateTicket={createTicket}
                creating={t.kind === "server" && creating === t.turn.public_id}
                onAnswer={answer}
                answering={t.kind === "server" && answering === t.turn.public_id}
                onRetry={retry}
              />
            ))
          )}
          <div ref={endRef} />
        </div>
      </div>
      <footer className="border-t border-[var(--border)] bg-[var(--bg)]">
        <div className="mx-auto max-w-3xl px-4 py-3 md:px-6">
          <Composer onSend={ask} disabled={busy} autoFocus />
          <p className="mt-2 text-xs text-[var(--text-muted)]">
            Every question is logged as a ticket. A person reviews anything the assistant isn&apos;t sure about.
          </p>
        </div>
      </footer>
    </div>
  );
}

function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
