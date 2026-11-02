"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useConversation, type Turn } from "@/lib/conversation";
import Composer from "@/components/Composer";
import NotificationBell from "@/components/NotificationBell";
import TurnView from "@/components/TurnView";
import Welcome from "@/components/Welcome";

export default function ChatPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const { turns, loaded, ask, createTicket, creating, answer, answering, retry } = useConversation(!!user);
  // The request on screen: a turn's key, or null for a new request.
  const [selected, setSelected] = useState<string | null>(null);
  // On a phone the list and a request take turns on screen.
  const [showList, setShowList] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  const current = turns.find((t) => t.key === selected) ?? null;
  const currentState = current?.kind === "server" ? current.turn.state : current?.kind;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [selected, currentState]);

  if (!user) return null;

  const busy = turns.some((t) => t.kind === "sending");
  const requests = [...turns].reverse();

  const open = (key: string | null) => {
    setSelected(key);
    setShowList(false);
  };

  const send = (text: string) => open(ask(text));

  return (
    <div className="flex h-dvh flex-col">
      <header className="border-b border-[var(--border)] bg-[var(--surface)]">
        <div className="flex items-center justify-between px-4 py-3 md:px-6">
          <p className="flex items-baseline gap-3">
            <span className="font-semibold">IT Help</span>
            <span className="hidden text-sm text-[var(--text-muted)] sm:inline">Service desk</span>
          </p>
          <div className="flex items-center gap-4 text-sm">
            <NotificationBell />
            <span className="hidden text-[var(--text-muted)] sm:inline">{user.username}</span>
            <button onClick={() => void logout()} className="text-[var(--text-muted)] hover:text-[var(--text)]">
              Sign out
            </button>
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside
          className={`${showList ? "flex" : "hidden"} w-full shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface)] md:flex md:w-80`}
        >
          <div className="p-3">
            <button
              onClick={() => open(null)}
              className={`btn w-full justify-center ${selected === null ? "btn-primary" : "btn-secondary"}`}
            >
              New request
            </button>
          </div>
          <p className="px-4 pb-1.5 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
            Your requests
          </p>
          <ul className="min-h-0 flex-1 overflow-y-auto">
            {loaded && requests.length === 0 && (
              <li className="px-4 py-3 text-sm text-[var(--text-muted)]">Nothing yet. Your questions will appear here.</li>
            )}
            {requests.map((t) => (
              <li key={t.key}>
                <button
                  onClick={() => open(t.key)}
                  aria-current={selected === t.key ? "true" : undefined}
                  className={`block w-full border-l-2 px-4 py-3 text-left transition-colors ${
                    selected === t.key
                      ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                      : "border-transparent hover:bg-[var(--surface-2)]"
                  }`}
                >
                  <span className="line-clamp-2 text-sm">{questionOf(t)}</span>
                  <RequestState turn={t} />
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section className={`${showList ? "hidden" : "flex"} min-w-0 flex-1 flex-col md:flex`}>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6 md:px-6">
              <button onClick={() => setShowList(true)} className="self-start text-sm text-[var(--text-muted)] md:hidden">
                ← Your requests
              </button>
              {current ? (
                <TurnView
                  turn={current}
                  onCreateTicket={createTicket}
                  creating={current.kind === "server" && creating === current.turn.public_id}
                  onAnswer={answer}
                  answering={current.kind === "server" && answering === current.turn.public_id}
                  onRetry={(key) => setSelected(retry(key))}
                />
              ) : (
                <Welcome name={user.username} onPick={send} />
              )}
              <div ref={endRef} />
            </div>
          </div>

          <footer className="border-t border-[var(--border)] bg-[var(--bg)]">
            <div className="mx-auto max-w-3xl px-4 py-3 md:px-6">
              {current ? (
                <p className="flex flex-wrap items-center justify-between gap-2 text-sm text-[var(--text-muted)]">
                  Something else, or more detail on this?
                  <button onClick={() => open(null)} className="btn btn-secondary">
                    Ask a new question
                  </button>
                </p>
              ) : (
                <>
                  <Composer onSend={send} disabled={busy} autoFocus />
                  <p className="mt-2 text-xs text-[var(--text-muted)]">
                    Every question is logged as a ticket. A person reviews anything the assistant isn&apos;t sure about.
                  </p>
                </>
              )}
            </div>
          </footer>
        </section>
      </div>
    </div>
  );
}

function questionOf(t: Turn): string {
  return t.kind === "server" ? t.turn.question_masked : t.text;
}

const STATE_LABEL: Record<string, { text: string; tone: string }> = {
  thinking: { text: "Looking for an answer…", tone: "text-[var(--text-muted)]" },
  answered: { text: "Answered", tone: "text-[var(--ok)]" },
  clarify: { text: "Needs your reply", tone: "font-medium text-[var(--warn)]" },
  suggest_ticket: { text: "No answer found", tone: "text-[var(--text-muted)]" },
  with_support: { text: "With support", tone: "text-[var(--text-muted)]" },
};

function RequestState({ turn }: { turn: Turn }) {
  if (turn.kind === "sending") return <span className="mt-1 block text-xs text-[var(--text-muted)]">Sending…</span>;
  if (turn.kind === "failed") return <span className="mt-1 block text-xs text-[var(--danger)]">Not sent</span>;
  const t = turn.turn;
  const label =
    t.state === "with_support"
      ? { text: t.resolved ? "Resolved" : `With support${t.status_name ? ` · ${t.status_name}` : ""}`, tone: t.resolved ? "text-[var(--ok)]" : "text-[var(--text-muted)]" }
      : STATE_LABEL[t.state];
  return (
    <span className="mt-1 flex items-center justify-between gap-2 text-xs">
      <span className={`min-w-0 truncate ${label.tone}`}>{label.text}</span>
      <span className="shrink-0 whitespace-nowrap font-mono text-[var(--text-muted)]">{t.public_id}</span>
    </span>
  );
}
