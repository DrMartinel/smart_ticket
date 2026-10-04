"use client";

import type { ChatTurnOut } from "@/lib/types/generated";
import { SLOW_AFTER_MS, type Turn } from "@/lib/conversation";
import { BookIcon, CheckIcon, ShieldIcon, SparkleIcon, TicketIcon } from "./icons";

// The masking placeholders core-api writes in place of PII, e.g. [EMAIL_1].
const PLACEHOLDER = /\[[A-Z]+(?:_[A-Z]+)*_\d+\]/;

export default function TurnView({
  turn,
  onCreateTicket,
  creating,
  onRetry,
}: {
  turn: Turn;
  onCreateTicket: (publicId: string) => void;
  creating: boolean;
  onRetry: (key: string) => void;
}) {
  if (turn.kind === "sending") {
    return (
      <>
        <Question text={turn.text} />
        <Reply>
          <Thinking label="Reading your question…" />
        </Reply>
      </>
    );
  }
  if (turn.kind === "failed") {
    return (
      <>
        <Question text={turn.text} />
        <Reply>
          <p className="text-[var(--danger)]">{turn.error}</p>
          <button onClick={() => onRetry(turn.key)} className="mt-2 text-sm font-medium text-[var(--accent)] hover:underline">
            Try again
          </button>
        </Reply>
      </>
    );
  }

  const t = turn.turn;
  return (
    <>
      <Question text={t.question_masked} masked={PLACEHOLDER.test(t.question_masked)} />
      <Reply>
        <Outcome turn={t} startedAt={turn.startedAt} onCreateTicket={onCreateTicket} creating={creating} />
      </Reply>
    </>
  );
}

function Question({ text, masked = false }: { text: string; masked?: boolean }) {
  return (
    <div className="turn-in flex flex-col items-end">
      <div className="brand-gradient max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md px-4 py-2.5 text-[15px] leading-6 text-white shadow-sm">
        {text}
      </div>
      {masked && (
        <p className="mt-1 flex items-center gap-1 text-xs text-[var(--text-muted)]">
          <ShieldIcon /> Personal details were hidden before anything else read this.
        </p>
      )}
    </div>
  );
}

function Reply({ children }: { children: React.ReactNode }) {
  return (
    <div className="turn-in flex items-start gap-3">
      <div className="brand-gradient mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full text-white">
        <SparkleIcon />
      </div>
      <div className="surface min-w-0 max-w-[85%] rounded-2xl rounded-tl-md px-4 py-3 text-[15px] leading-6">{children}</div>
    </div>
  );
}

function Thinking({ label, slow = false }: { label: string; slow?: boolean }) {
  return (
    <div role="status" className="flex flex-col gap-1">
      <div className="flex items-center gap-3">
        <span className="flex gap-1" aria-hidden>
          <span className="dot" />
          <span className="dot" />
          <span className="dot" />
        </span>
        <span className="text-[var(--text-muted)]">{label}</span>
      </div>
      {slow && (
        <p className="text-xs text-[var(--text-muted)]">This is taking longer than usual. You can leave; it will be here when you return.</p>
      )}
    </div>
  );
}

function Outcome({
  turn,
  startedAt,
  onCreateTicket,
  creating,
}: {
  turn: ChatTurnOut;
  startedAt: number;
  onCreateTicket: (publicId: string) => void;
  creating: boolean;
}) {
  switch (turn.state) {
    case "thinking":
      return <Thinking label="Searching the knowledge base…" slow={Date.now() - startedAt > SLOW_AFTER_MS} />;

    case "answered":
      if (!turn.answer) return <p>Answered.</p>;
      return (
        <div className="flex flex-col gap-3">
          <p className="whitespace-pre-wrap break-words">{turn.answer.text}</p>
          <figure className="rounded-xl border-l-[3px] border-[var(--accent)] bg-[var(--surface-2)] px-3 py-2">
            <blockquote className="text-sm italic text-[var(--text-muted)]">“{turn.answer.quote}”</blockquote>
            <figcaption className="mt-1.5 flex items-center gap-1.5 text-xs font-medium">
              <BookIcon className="h-3.5 w-3.5 text-[var(--accent)]" />
              {turn.answer.kb_url ? (
                <a href={turn.answer.kb_url} target="_blank" rel="noreferrer" className="text-[var(--accent)] hover:underline">
                  {turn.answer.kb_title}
                </a>
              ) : (
                <span>{turn.answer.kb_title}</span>
              )}
            </figcaption>
          </figure>
          <p className="text-xs text-[var(--text-muted)]">
            From an approved knowledge-base page. Still stuck? Ask again with more detail and I&apos;ll offer a ticket.
          </p>
        </div>
      );

    case "suggest_ticket":
      return (
        <div className="flex flex-col gap-3">
          <p>
            I couldn&apos;t find an answer I&apos;m confident in, so I&apos;d rather not guess. A person on the support team can
            take this from here.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={() => onCreateTicket(turn.public_id)}
              disabled={creating}
              className="brand-gradient inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:brightness-110 disabled:opacity-50"
            >
              <TicketIcon />
              {creating ? "Creating ticket…" : "Create a ticket"}
            </button>
            <span className="text-xs text-[var(--text-muted)]">Your question goes to support as written above.</span>
          </div>
        </div>
      );

    case "with_support":
      return (
        <div className="flex items-start gap-3">
          <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[var(--ok-soft)] text-[var(--ok)]">
            <CheckIcon className="h-3.5 w-3.5" />
          </span>
          <div>
            <p>
              Ticket <span className="font-mono text-sm font-semibold">{turn.public_id}</span> is with the support team.
            </p>
            <p className="text-sm text-[var(--text-muted)]">A technician will follow up with you.</p>
          </div>
        </div>
      );
  }
}
