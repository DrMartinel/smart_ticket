"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useConversation } from "@/lib/conversation";
import Composer from "@/components/Composer";
import TurnView from "@/components/TurnView";
import Welcome from "@/components/Welcome";
import { SparkleIcon } from "@/components/icons";

export default function ChatPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const { turns, loaded, ask, createTicket, creating, retry } = useConversation(!!user);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  // Follow the conversation as it grows.
  const lastKey = turns.at(-1)?.key;
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [lastKey, turns.length]);

  if (!user) return null;

  const busy = turns.some((t) => t.kind === "sending");

  return (
    <div className="flex h-dvh flex-col">
      <header className="sticky top-0 z-10 border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--bg)_80%,transparent)] backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span className="brand-gradient grid h-8 w-8 place-items-center rounded-lg text-white">
              <SparkleIcon />
            </span>
            <div className="leading-tight">
              <p className="text-sm font-semibold">IT Help</p>
              <p className="text-xs text-[var(--text-muted)]">Answers from approved help pages</p>
            </div>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden text-[var(--text-muted)] sm:inline">{user.username}</span>
            <button
              onClick={logout}
              className="rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs transition hover:bg-[var(--surface-2)]"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-5 px-4 py-6">
          {loaded && turns.length === 0 && <Welcome name={user.username} onPick={ask} />}
          {turns.map((t) => (
            <div key={t.key} className="flex flex-col gap-3">
              <TurnView
                turn={t}
                onCreateTicket={createTicket}
                creating={t.kind === "server" && creating === t.turn.public_id}
                onRetry={retry}
              />
            </div>
          ))}
          <div ref={endRef} />
        </div>
      </main>

      <footer className="bg-gradient-to-t from-[var(--bg)] via-[var(--bg)] to-transparent pt-2">
        <div className="mx-auto max-w-3xl px-4 pb-4">
          <Composer onSend={ask} disabled={busy} autoFocus />
          <p className="mt-2 text-center text-[11px] text-[var(--text-muted)]">
            Every question is logged as a ticket. A person reviews anything the assistant isn&apos;t sure about.
          </p>
        </div>
      </footer>
    </div>
  );
}
