"use client";

import Link from "next/link";
import type { AgentActionOut, AgentReceiptOut, ChatTurnOut } from "@/lib/types/generated";
import type { ActionResult, AgentRow } from "@/lib/agent";
import { PLACEHOLDER, Question, Reply, Working } from "./TurnView";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/states";

// What each chat tool's change is called in a receipt or a confirmation card.
const TOOL_LABEL: Record<string, string> = {
  ask_helpdesk: "Asked the helpdesk",
  answer_clarification: "Answered the helpdesk's question",
  request_ticket: "Asked for a ticket",
  reply_to_my_ticket: "Reply to your ticket",
  reopen_my_ticket: "Reopen your ticket",
};

const OUTCOME: Record<AgentReceiptOut["outcome"], { label: string; variant: "ok" | "info" | "warn" | "danger" }> = {
  done: { label: "Done", variant: "ok" },
  awaiting_confirmation: { label: "Needs your OK", variant: "info" },
  draft_waiting: { label: "Draft waiting", variant: "info" },
  refused: { label: "Not allowed", variant: "warn" },
  failed: { label: "Failed", variant: "danger" },
  unknown: { label: "Not sure it went through", variant: "warn" },
};

const TICKET_IN_PATH = /\/tickets\/([^/]+)/;

function ticketIn(path: string): string | undefined {
  const segment = TICKET_IN_PATH.exec(path)?.[1];
  if (!segment) return undefined;
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

export default function AgentTurnView({
  row,
  pending,
  handoff,
  busyAction,
  actionError,
  results,
  creating,
  createError,
  onConfirm,
  onDismiss,
  onCreateTicket,
  onRetry,
}: {
  row: AgentRow;
  pending: AgentActionOut[];
  handoff: ChatTurnOut | undefined;
  busyAction: string | null;
  actionError: Record<string, string>;
  results: Record<string, ActionResult>;
  creating: string | null;
  createError: Record<string, string>;
  onConfirm: (action: AgentActionOut) => void;
  onDismiss: (action: AgentActionOut) => void;
  onCreateTicket: (publicId: string) => void;
  onRetry: (key: string) => void;
}) {
  if (row.kind === "ended") {
    return (
      <p role="status" className="border-t border-border pt-3 text-center text-xs text-muted-foreground">
        That conversation ended, so this starts a new one.
      </p>
    );
  }
  if (row.kind === "sending") {
    return (
      <>
        <Question text={row.text} />
        <Reply>
          <Working label="Sending" />
        </Reply>
      </>
    );
  }
  if (row.kind === "failed") {
    return (
      <>
        <Question text={row.text} />
        <Reply>
          <ErrorState compact title={row.error} onRetry={() => onRetry(row.key)} />
        </Reply>
      </>
    );
  }

  const t = row.turn;
  const asked = t.receipts.filter((r) => r.outcome === "awaiting_confirmation" && r.action_id);
  const cards = asked.flatMap((r) => pending.filter((a) => a.action_id === r.action_id));
  const answered = asked.flatMap((r) => (r.action_id && results[r.action_id] ? [results[r.action_id]] : []));
  return (
    <>
      <Question text={t.message_masked} masked={PLACEHOLDER.test(t.message_masked)} at={t.queued_at} />
      <Reply>
        {t.state === "queued" || t.state === "running" ? (
          <Working label="The assistant is working on it" />
        ) : (
          <div className="flex flex-col gap-3">
            <p className="whitespace-pre-wrap">{t.reply}</p>
            {t.receipts.length > 0 && (
              <ul aria-label="What the assistant did" className="flex flex-col gap-1.5 border-t border-border pt-3">
                {t.receipts.map((r, i) => (
                  <Receipt key={i} receipt={r} result={r.action_id ? results[r.action_id] : undefined} />
                ))}
              </ul>
            )}
            {cards.map((a) => (
              <ConfirmCard
                key={a.action_id}
                action={a}
                busy={busyAction === a.action_id}
                error={actionError[a.action_id]}
                onConfirm={() => onConfirm(a)}
                onDismiss={() => onDismiss(a)}
              />
            ))}
            {answered.map((result, i) => (
              <p key={i} role="status" className="text-sm">
                {result.text}{" "}
                {result.ticket && (
                  <Link href={`/tickets/${encodeURIComponent(result.ticket)}`} className="num text-primary hover:underline">
                    {result.ticket}
                  </Link>
                )}
              </p>
            ))}
            {t.state === "handed_off" && t.handoff_ticket && (
              <Handoff
                publicId={t.handoff_ticket}
                ticket={handoff}
                busy={creating === t.handoff_ticket}
                error={createError[t.handoff_ticket]}
                onCreateTicket={onCreateTicket}
              />
            )}
          </div>
        )}
      </Reply>
    </>
  );
}

function Receipt({ receipt, result }: { receipt: AgentReceiptOut; result: ActionResult | undefined }) {
  const outcome = result ? { label: result.label, variant: result.tone } : OUTCOME[receipt.outcome];
  const ticket = ticketIn(receipt.path);
  return (
    <li className="flex flex-wrap items-center gap-2 text-sm">
      <Badge variant={outcome.variant}>{outcome.label}</Badge>
      <span>{TOOL_LABEL[receipt.tool] ?? receipt.tool}</span>
      {ticket && (
        <Link href={`/tickets/${encodeURIComponent(ticket)}`} className="num text-primary hover:underline">
          {ticket}
        </Link>
      )}
    </li>
  );
}

function ConfirmCard({
  action,
  busy,
  error,
  onConfirm,
  onDismiss,
}: {
  action: AgentActionOut;
  busy: boolean;
  error: string | undefined;
  onConfirm: () => void;
  onDismiss: () => void;
}) {
  const payload = (action.arguments.payload ?? {}) as Record<string, unknown>;
  const text = typeof payload.body === "string" ? payload.body : typeof payload.reason === "string" ? payload.reason : null;
  const ticket = ticketIn(action.path);
  return (
    <Card className="flex flex-col gap-3 border-info/40 px-4 py-3" aria-label="Confirm this change">
      <p className="text-sm font-medium">
        {TOOL_LABEL[action.tool] ?? action.tool}
        {ticket && <span className="num"> · {ticket}</span>}
      </p>
      {text && <blockquote className="whitespace-pre-wrap rounded-md bg-muted px-3 py-2 text-sm">{text}</blockquote>}
      <p className="text-xs text-muted-foreground">
        Nothing is sent until you choose Send. This expires at{" "}
        {new Date(action.expires_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}.
      </p>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button size="sm" onClick={onConfirm} disabled={busy}>
          Send
        </Button>
        <Button size="sm" variant="ghost" onClick={onDismiss} disabled={busy}>
          Cancel
        </Button>
      </div>
    </Card>
  );
}

function Handoff({
  publicId,
  ticket,
  busy,
  error,
  onCreateTicket,
}: {
  publicId: string;
  ticket: ChatTurnOut | undefined;
  busy: boolean;
  error: string | undefined;
  onCreateTicket: (publicId: string) => void;
}) {
  const link = (
    <Link href={`/tickets/${encodeURIComponent(publicId)}`} className="num text-primary hover:underline">
      {publicId}
    </Link>
  );
  if (!ticket || ticket.state === "thinking") return <Working label="Passing this to the helpdesk" />;
  if (ticket.state === "suggest_ticket") {
    return (
      <div className="flex flex-col gap-2 border-t border-border pt-3 text-sm">
        <p>A person can take this from here. Open a ticket with your message?</p>
        {error && (
          <p role="alert" className="text-danger">
            {error}
          </p>
        )}
        <div>
          <Button size="sm" onClick={() => onCreateTicket(publicId)} disabled={busy}>
            Open a ticket
          </Button>
        </div>
      </div>
    );
  }
  return <p className="border-t border-border pt-3 text-sm">Your message is with support as {link}.</p>;
}
