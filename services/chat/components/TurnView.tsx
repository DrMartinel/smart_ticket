"use client";

import { useState } from "react";
import type { ChatClarificationOut, ChatTurnOut } from "@/lib/types/generated";
import { SLOW_AFTER_MS, type Turn } from "@/lib/conversation";
import { BookIcon, CheckIcon, ShieldIcon, SparkleIcon, TicketIcon } from "./icons";

// The masking placeholders core-api writes in place of PII, e.g. [EMAIL_1].
const PLACEHOLDER = /\[[A-Z]+(?:_[A-Z]+)*_\d+\]/;

export default function TurnView({
  turn,
  onCreateTicket,
  creating,
  onRetry,
  onAnswer,
  answering,
}: {
  turn: Turn;
  onCreateTicket: (publicId: string) => void;
  creating: boolean;
  onRetry: (key: string) => void;
  onAnswer: (publicId: string, answer: string) => void;
  answering: boolean;
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
  const asked = t.state === "clarify" ? null : t.clarification;
  return (
    <>
      <Question text={t.question_masked} masked={PLACEHOLDER.test(t.question_masked)} />
      {asked && (
        // A question asked earlier: answered, or closed unanswered. Shown
        // as the exchange it was, before what came of it.
        <>
          <Reply>
            <p>{asked.question}</p>
          </Reply>
          {asked.answer_masked && (
            <Question text={asked.answer_masked} masked={PLACEHOLDER.test(asked.answer_masked)} />
          )}
        </>
      )}
      <Reply>
        {t.state === "clarify" && t.clarification ? (
          <ClarifyCard
            clarification={t.clarification}
            onAnswer={(text) => onAnswer(t.public_id, text)}
            answering={answering}
            onCreateTicket={() => onCreateTicket(t.public_id)}
            creating={creating}
          />
        ) : (
          <Outcome turn={t} startedAt={turn.startedAt} onCreateTicket={onCreateTicket} creating={creating} />
        )}
      </Reply>
    </>
  );
}

// The router chose to ask which of the shown pages the requester means
// (ADR-0023). Tapping a page answers with its title; typing is for anything
// else. Asking for a person instead carries out the held decision.
function ClarifyCard({
  clarification,
  onAnswer,
  answering,
  onCreateTicket,
  creating,
}: {
  clarification: ChatClarificationOut;
  onAnswer: (text: string) => void;
  answering: boolean;
  onCreateTicket: () => void;
  creating: boolean;
}) {
  const [text, setText] = useState("");
  const busy = answering || creating;
  const send = () => {
    const answer = text.trim();
    if (answer && !busy) onAnswer(answer);
  };

  return (
    <div className="flex flex-col gap-3">
      <p>{clarification.question}</p>
      {clarification.options.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {clarification.options.map((title) => (
            <button
              key={title}
              onClick={() => onAnswer(title)}
              disabled={busy}
              className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] px-3 py-1.5 text-left text-sm transition hover:border-[var(--accent)] disabled:opacity-50"
            >
              {title}
            </button>
          ))}
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="flex gap-2"
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={2000}
          disabled={busy}
          placeholder="Or describe it in your own words"
          aria-label="Your answer"
          className="min-w-0 flex-1 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm outline-none focus:border-[var(--accent)]"
        />
        <button
          type="submit"
          disabled={busy || !text.trim()}
          className="brand-gradient rounded-xl px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          {answering ? "Sending…" : "Send"}
        </button>
      </form>
      <button
        onClick={onCreateTicket}
        disabled={busy}
        className="self-start text-xs text-[var(--text-muted)] underline-offset-2 hover:underline disabled:opacity-50"
      >
        {creating ? "Creating ticket…" : "Talk to a person instead"}
      </button>
    </div>
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

function AnswerText({ text }: { text: string }) {
  const parts = splitSteps(text);
  if (!parts) return <p className="whitespace-pre-wrap break-words">{text}</p>;
  return (
    <div className="flex flex-col gap-2 break-words">
      {parts.intro && <p>{parts.intro}</p>}
      <ol className="list-decimal space-y-1 pl-5 marker:text-[var(--text-muted)]">
        {parts.steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
      {parts.outro && <p>{parts.outro}</p>}
    </div>
  );
}

// The model writes steps inline ("…these steps: 1. Do this. 2. Do that.").
// Only markers numbered 1, 2, 3… in order count as steps, so a stray
// "Windows 10. " never splits the text; fewer than two leaves it as written.
// The last step keeps its first sentence, and whatever follows it ("If the
// issue persists, …") is the closing paragraph, not part of the step.
function splitSteps(text: string): { intro: string; steps: string[]; outro: string } | null {
  if (text.includes("\n")) return null;
  const marks: { start: number; end: number }[] = [];
  const marker = /(?:^|\s)(\d{1,2})\.\s+/g;
  for (let m = marker.exec(text); m; m = marker.exec(text)) {
    if (Number(m[1]) === marks.length + 1) marks.push({ start: m.index, end: m.index + m[0].length });
  }
  if (marks.length < 2) return null;

  const steps = marks.map((mk, i) => text.slice(mk.end, marks[i + 1]?.start ?? text.length).trim());
  const last = steps[steps.length - 1].match(/^(.*?[.!?])\s+([A-Z][\s\S]*)$/);
  let outro = "";
  if (last) {
    steps[steps.length - 1] = last[1];
    outro = last[2];
  }
  return { intro: text.slice(0, marks[0].start).trim(), steps, outro };
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
          <AnswerText text={turn.answer.text} />
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

    case "clarify":
      // Rendered by ClarifyCard; reached only without the question itself.
      return <p>Please answer the question above.</p>;

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
