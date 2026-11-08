"use client";

import Link from "next/link";
import type { AgentActionOut, AgentReceiptOut, ChatTurnOut } from "@/lib/types/generated";
import type { AgentRow } from "@/lib/agent";
import { Question, Reply, Working } from "./TurnView";
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
};

const TICKET_IN_PATH = /\/tickets\/([^/]+)/;

export default function AgentTurnView({
  row,
  pending,
  handoff,
  busyAction,
  actionError,
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
  onConfirm: (action: AgentActionOut) => void;
  onDismiss: (action: AgentActionOut) => void;
  onCreateTicket: (publicId: string) => void;
  onRetry: (key: string) => void;
}) {
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
  const cards = t.receipts.flatMap((r) =>
    r.outcome === "awaiting_confirmation" ? pending.filter((a) => a.action_id === r.action_id) : [],
  );
  return (
    <>
      <Question text={t.message_masked} masked={/\[[A-Z_]+_\d+\]/.test(t.message_masked)} at={t.queued_at} />
      <Reply>
        {t.state === "queued" || t.state === "running" ? (
          <Working label="The assistant is working on it" />
        ) : (
          <div className="flex flex-col gap-3">
            <p className="whitespace-pre-wrap">{t.reply}</p>
            {t.receipts.length > 0 && (
              <ul aria-label="What the assistant did" className="flex flex-col gap-1.5 border-t border-border pt-3">
                {t.receipts.map((r, i) => (
                  <Receipt key={i} receipt={r} />
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
            {t.state === "handed_off" && t.handoff_ticket && (
              <Handoff publicId={t.handoff_ticket} ticket={handoff} onCreateTicket={onCreateTicket} />
            )}
          </div>
        )}
      </Reply>
    </>
  );
}

function Receipt({ receipt }: { receipt: AgentReceiptOut }) {
  const outcome = OUTCOME[receipt.outcome];
  const ticket = TICKET_IN_PATH.exec(receipt.path)?.[1];
  return (
    <li className="flex flex-wrap items-center gap-2 text-sm">
      <Badge variant={outcome.variant}>{outcome.label}</Badge>
      <span>{TOOL_LABEL[receipt.tool] ?? receipt.tool}</span>
      {ticket && (
        <Link href={`/tickets/${encodeURIComponent(ticket)}`} className="num text-primary hover:underline">
          {decodeURIComponent(ticket)}
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
  const ticket = TICKET_IN_PATH.exec(action.path)?.[1];
  return (
    <Card className="flex flex-col gap-3 border-info/40 px-4 py-3" aria-label="Confirm this change">
      <p className="text-sm font-medium">
        {TOOL_LABEL[action.tool] ?? action.tool}
        {ticket && <span className="num"> · {decodeURIComponent(ticket)}</span>}
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
  onCreateTicket,
}: {
  publicId: string;
  ticket: ChatTurnOut | undefined;
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
        <div>
          <Button size="sm" onClick={() => onCreateTicket(publicId)}>
            Open a ticket
          </Button>
        </div>
      </div>
    );
  }
  return <p className="border-t border-border pt-3 text-sm">Your message is with support as {link}.</p>;
}
