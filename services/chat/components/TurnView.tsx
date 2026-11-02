"use client";

import Link from "next/link";
import { useState } from "react";
import type { ChatClarificationOut, ChatTurnOut } from "@/lib/types/generated";
import { SLOW_AFTER_MS, type Turn } from "@/lib/conversation";
import AnswerText, { InlineText } from "./AnswerText";
import { ArrowUpRightIcon, CheckIcon } from "./icons";
import IncidentBanner from "./IncidentBanner";
import Rating from "./Rating";
import ReopenBox from "./ReopenBox";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

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
          <Working label="Reading your question" />
        </Reply>
      </>
    );
  }
  if (turn.kind === "failed") {
    return (
      <>
        <Question text={turn.text} />
        <Reply>
          <p className="text-danger">{turn.error}</p>
          <Button variant="outline" onClick={() => onRetry(turn.key)} className="mt-3">
            Try again
          </Button>
        </Reply>
      </>
    );
  }

  const t = turn.turn;
  const asked = t.state === "clarify" ? null : t.clarification;
  return (
    <>
      <Question text={t.question_masked} masked={PLACEHOLDER.test(t.question_masked)} at={t.created_at} ticket={t.public_id} />
      {asked && (
        // A question asked earlier: answered, or closed unanswered. Shown
        // as the exchange it was, before what came of it.
        <>
          <Reply>
            <p>{asked.question}</p>
          </Reply>
          {asked.answer_masked && <Question text={asked.answer_masked} masked={PLACEHOLDER.test(asked.answer_masked)} />}
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

// The router chose to ask which page the requester means (ADR-0023). The
// pages are core-api's, from Jev's ranking; picking one answers with its
// title. "None of these" opens a box to say it in their own words, and
// asking for a person carries out the held decision.
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
  const [typing, setTyping] = useState(false);
  const busy = answering || creating;
  const send = () => {
    const answer = text.trim();
    if (answer && !busy) onAnswer(answer);
  };

  return (
    <div className="flex flex-col gap-3">
      <p>{clarification.question}</p>
      {clarification.options.length > 0 && (
        <ul className="divide-y divide-border overflow-hidden rounded-md border border-border">
          {clarification.options.map((title) => (
            <li key={title}>
              <button
                onClick={() => onAnswer(title)}
                disabled={busy}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm transition-colors hover:bg-muted disabled:opacity-50"
              >
                {title}
                <span aria-hidden className="text-muted-foreground">
                  →
                </span>
              </button>
            </li>
          ))}
          {!typing && (
            <li>
              <button
                onClick={() => setTyping(true)}
                disabled={busy}
                className="w-full px-3 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
              >
                None of these
              </button>
            </li>
          )}
        </ul>
      )}
      {(typing || clarification.options.length === 0) && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
          className="flex gap-2"
        >
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={2000}
            disabled={busy}
            autoFocus
            placeholder="Describe what you need in your own words"
            aria-label="Your answer"
            className="min-w-0 flex-1 text-sm"
          />
          <Button type="submit" disabled={busy || !text.trim()}>
            {answering ? "Sending…" : "Send"}
          </Button>
        </form>
      )}
      <Button variant="link" size="inline" onClick={onCreateTicket} disabled={busy} className="self-start underline">
        {creating ? "Creating ticket…" : "Talk to a person instead"}
      </Button>
    </div>
  );
}

function Question({
  text,
  masked = false,
  at,
  ticket,
}: {
  text: string;
  masked?: boolean;
  at?: string;
  ticket?: string;
}) {
  return (
    <article className="flex flex-col gap-1.5">
      <Byline who="You" at={at} ticket={ticket} />
      <div className="whitespace-pre-wrap break-words rounded-lg bg-muted px-4 py-3 text-[15px] leading-6">
        {text}
      </div>
      {masked && (
        <p className="text-xs text-muted-foreground">
          Personal details (shown in brackets) were removed before anyone else read this.
        </p>
      )}
    </article>
  );
}

function Reply({ children }: { children: React.ReactNode }) {
  return (
    <article className="flex flex-col gap-1.5">
      <Byline who="IT Help" />
      <Card className="border-l-2 border-l-primary px-4 py-3 text-[15px] leading-6">{children}</Card>
    </article>
  );
}

function Byline({ who, at, ticket }: { who: string; at?: string; ticket?: string }) {
  return (
    <p className="flex items-baseline gap-2 text-xs text-muted-foreground">
      <span className="font-medium text-foreground">{who}</span>
      {at && <time dateTime={at}>{formatTime(at)}</time>}
      {ticket && <span className="font-mono">{ticket}</span>}
    </p>
  );
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function Working({ label, slow = false }: { label: string; slow?: boolean }) {
  return (
    <div role="status" className="flex flex-col gap-2">
      <p className="text-muted-foreground">{label}…</p>
      <span className="progress" aria-hidden />
      {slow && (
        <p className="text-xs text-muted-foreground">
          This is taking longer than usual. You can leave; the answer will be here when you return.
        </p>
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
      return <Working label="Searching the help pages" slow={Date.now() - startedAt > SLOW_AFTER_MS} />;

    case "answered":
      if (!turn.answer) return <p>Answered.</p>;
      return (
        <div className="flex flex-col gap-4">
          <AnswerText text={turn.answer.text} />
          <figure className="border-t border-border pt-3 text-sm">
            <figcaption className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Source</figcaption>
            {turn.answer.kb_url ? (
              <a
                href={turn.answer.kb_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 font-medium text-primary underline-offset-2 hover:underline"
              >
                {turn.answer.kb_title}
                <ArrowUpRightIcon />
              </a>
            ) : (
              <span className="font-medium">{turn.answer.kb_title}</span>
            )}
            <blockquote className="answer mt-1.5 border-l border-border-strong pl-3 text-muted-foreground">
              <InlineText text={turn.answer.quote} />
            </blockquote>
          </figure>
          <AnswerFeedback publicId={turn.public_id} />
        </div>
      );

    case "clarify":
      // Rendered by ClarifyCard; reached only without the question itself.
      return <p>Please answer the question above.</p>;

    case "suggest_ticket":
      return (
        <div className="flex flex-col gap-3">
          <p>
            None of the approved help pages answers this closely enough, so rather than guess, this should go to the
            support team.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => onCreateTicket(turn.public_id)} disabled={creating}>
              {creating ? "Creating ticket…" : "Create a ticket"}
            </Button>
            <span className="text-xs text-muted-foreground">Support receives your question as written above.</span>
          </div>
        </div>
      );

    case "with_support":
      if (turn.incident) {
        return (
          <div className="flex flex-col gap-3">
            <IncidentBanner incident={turn.incident} publicId={turn.public_id} />
            <p>
              Đây là sự cố đội IT đang khắc phục; câu hỏi của bạn đã được gắn vào đó, bạn sẽ nhận cập nhật tiếp theo tại đây và qua email.
            </p>
          </div>
        );
      }
      return (
        <div className="flex items-start gap-2.5">
          <CheckIcon className="mt-1 h-4 w-4 shrink-0 text-ok" />
          <div>
            <p>
              Ticket <span className="font-mono font-medium">{turn.public_id}</span> is with the support team.
            </p>
            <p className="text-sm text-muted-foreground">A technician will follow up with you.</p>
            <Link href={`/tickets/${turn.public_id}`} className="text-sm text-primary underline-offset-2 hover:underline">
              Xem trong Đơn của tôi · Open in My tickets →
            </Link>
          </div>
        </div>
      );
  }
}

// "Đã giải quyết?" under an auto-reply (F3 · Answer card 10-500): fixed opens the rating, not
// fixed reopens the ticket for a person.
function AnswerFeedback({ publicId }: { publicId: string }) {
  const [choice, setChoice] = useState<"fixed" | "not_fixed" | null>(null);
  return (
    <div className="flex flex-col gap-3 border-t border-border pt-3">
      {choice === null && (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setChoice("fixed")}>
            ✓ Đã giải quyết · Fixed
          </Button>
          <Button variant="outline" onClick={() => setChoice("not_fixed")}>
            Chưa giải quyết được · Still not fixed
          </Button>
        </div>
      )}
      {choice === "fixed" && <Rating publicId={publicId} current={null} until={null} compact />}
      {choice === "not_fixed" && <ReopenBox publicId={publicId} until={null} />}
      <p className="text-xs text-muted-foreground">
        {publicId} · From an approved knowledge-base page. &ldquo;Still not fixed&rdquo; reopens this ticket for a person
        within 7 days.
      </p>
    </div>
  );
}
