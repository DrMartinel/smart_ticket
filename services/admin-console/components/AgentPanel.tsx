"use client";

// The console assistant (F15): a side panel on every Workspace page. Reads run as the person;
// a change it proposes waits for Send here, and a judgement waits as a draft on its ticket.

import Link from "next/link";
import { useState } from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { Bot, Plus, X } from "lucide-react";
import { TOOL_LABEL, useAgentConversation, type AgentRow } from "@/lib/agent";
import { reasonText } from "@/lib/explain";
import type { AgentActionOut, AgentReceiptOut } from "@/lib/types/generated";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";

const OUTCOME: Record<AgentReceiptOut["outcome"], { label: string; variant: "ok" | "info" | "warn" | "danger" }> = {
  done: { label: "Done", variant: "ok" },
  awaiting_confirmation: { label: "Needs your OK", variant: "info" },
  draft_waiting: { label: "Draft waiting", variant: "info" },
  refused: { label: "Not allowed", variant: "warn" },
  failed: { label: "Failed", variant: "danger" },
};

/** The page a call's path is about: a ticket, or a review item (which opens its ticket). */
function pageOf(path: string): { href: string; label: string } | null {
  const ticket = /\/api\/tickets\/([^/]+)/.exec(path)?.[1];
  if (ticket) return { href: `/tickets/${ticket}`, label: decodeURIComponent(ticket) };
  const item = /\/api\/review\/items\/([^/]+)/.exec(path)?.[1];
  if (item) return { href: `/review/${item}`, label: "the review item" };
  return null;
}

export default function AgentPanel() {
  const [open, setOpen] = useState(false);
  const agent = useAgentConversation(open);
  const [draft, setDraft] = useState("");

  const submit = () => {
    const text = draft.trim();
    if (!text || agent.busy) return;
    agent.send(text);
    setDraft("");
  };

  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Trigger asChild>
        <Button size="sm" aria-label="Open the assistant" className="fixed right-4 bottom-4 z-30 shadow-float">
          <Bot aria-hidden />
          <span className="hidden sm:inline">Assistant</span>
        </Button>
      </DialogPrimitive.Trigger>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Content
          onInteractOutside={(e) => e.preventDefault()}
          className="fixed inset-y-0 right-0 z-50 flex w-[min(420px,100vw)] flex-col border-l border-border bg-card shadow-float duration-200 data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right data-[state=open]:animate-in data-[state=open]:slide-in-from-right"
        >
          <div className="flex h-14 items-center justify-between gap-2 border-b border-border pr-2 pl-4">
            <DialogPrimitive.Title className="text-sm font-semibold">Assistant</DialogPrimitive.Title>
            <DialogPrimitive.Description className="sr-only">
              Ask the assistant to look things up or prepare changes for you to confirm.
            </DialogPrimitive.Description>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="sm" onClick={() => void agent.startNew()} disabled={agent.busy}>
                <Plus aria-hidden /> New
              </Button>
              <DialogPrimitive.Close aria-label="Close the assistant" className="inline-flex size-9 items-center justify-center rounded-md hover:bg-muted">
                <X className="size-4" />
              </DialogPrimitive.Close>
            </div>
          </div>
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 text-sm">
            {agent.rows.length === 0 ? (
              <p className="text-muted-foreground">
                Ask about tickets or your review queue. The assistant acts as you; it asks before any change, and
                decisions it suggests wait as drafts on the ticket for you to apply.
              </p>
            ) : (
              agent.rows.map((row) => (
                <Turn
                  key={row.key}
                  row={row}
                  pending={agent.pending}
                  busyAction={agent.busyAction}
                  actionError={agent.actionError}
                  onConfirm={agent.confirm}
                  onDismiss={agent.dismiss}
                />
              ))
            )}
          </div>
          <form
            className="flex flex-col gap-2 border-t border-border p-3"
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
              maxLength={4000}
              rows={2}
              aria-label="Message to the assistant"
              placeholder="e.g. Which items in my review queue look straightforward?"
            />
            <div className="flex justify-end">
              <Button type="submit" size="sm" disabled={agent.busy || !draft.trim()}>
                Send
              </Button>
            </div>
          </form>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function Turn({
  row,
  pending,
  busyAction,
  actionError,
  onConfirm,
  onDismiss,
}: {
  row: AgentRow;
  pending: AgentActionOut[];
  busyAction: string | null;
  actionError: Record<string, string>;
  onConfirm: (a: AgentActionOut) => void;
  onDismiss: (a: AgentActionOut) => void;
}) {
  const asked = row.kind === "server" ? row.turn.message_masked : row.text;
  return (
    <div className="flex flex-col gap-2">
      <p className="ml-auto max-w-[90%] whitespace-pre-wrap rounded-md bg-muted px-3 py-2">{asked}</p>
      {row.kind === "sending" || (row.kind === "server" && (row.turn.state === "queued" || row.turn.state === "running")) ? (
        <p role="status" className="text-muted-foreground">
          Working on it…
        </p>
      ) : row.kind === "failed" ? (
        <p role="alert" className="text-danger">
          {row.error}
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="whitespace-pre-wrap">{row.turn.reply}</p>
          {row.turn.state === "handed_off" && row.turn.stop_reason && (
            <p className="text-xs text-muted-foreground">Stopped: {reasonText(row.turn.stop_reason)}</p>
          )}
          {row.turn.receipts.length > 0 && (
            <ul aria-label="What the assistant did" className="flex flex-col gap-1.5 border-t border-border pt-2">
              {row.turn.receipts.map((r, i) => {
                const page = pageOf(r.path);
                return (
                  <li key={i} className="flex flex-wrap items-center gap-2">
                    <Badge variant={OUTCOME[r.outcome].variant}>{OUTCOME[r.outcome].label}</Badge>
                    <span>{TOOL_LABEL[r.tool] ?? r.tool}</span>
                    {page && (
                      <Link href={page.href} className="text-primary hover:underline">
                        {page.label}
                      </Link>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {row.turn.receipts.flatMap((r) =>
            r.outcome === "awaiting_confirmation"
              ? pending
                  .filter((a) => a.action_id === r.action_id)
                  .map((a) => (
                    <ConfirmCard
                      key={a.action_id}
                      action={a}
                      busy={busyAction === a.action_id}
                      error={actionError[a.action_id]}
                      onConfirm={() => onConfirm(a)}
                      onDismiss={() => onDismiss(a)}
                    />
                  ))
              : [],
          )}
        </div>
      )}
    </div>
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
  const page = pageOf(action.path);
  return (
    <Card className="flex flex-col gap-2 border-info/40 px-3 py-2.5" aria-label="Confirm this change">
      <p className="font-medium">
        {TOOL_LABEL[action.tool] ?? action.tool}
        {page && <span className="font-normal text-muted-foreground"> · {page.label}</span>}
      </p>
      {typeof payload.body === "string" && (
        <blockquote className="whitespace-pre-wrap rounded-md bg-muted px-3 py-2">{payload.body}</blockquote>
      )}
      {error && (
        <p role="alert" className="text-danger">
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
