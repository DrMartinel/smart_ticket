"use client";

// The assistant (F15) is the chat: it answers questions from the approved help pages, opens
// tickets, and looks up and acts on the employee's own tickets. Every change it proposes waits
// for the employee's Send; a turn it can't finish goes to a person.

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { Bot, Plus } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { AGENT_MESSAGE_MAX, AGENT_MESSAGE_MIN } from "@/lib/agent";
import { AGENT_USE, INFRA_READ_OWN } from "@/lib/session";
import { useAssistant } from "@/components/AssistantProvider";
import AgentTurnView from "@/components/AgentTurnView";
import Composer from "@/components/Composer";
import Welcome from "@/components/Welcome";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/states";

// Shown to holders of infra:read:own only (F17 BR-F17-27).
const NAME_THE_RESOURCE = {
  vi: "Nếu vấn đề liên quan đến máy chủ, ổ đĩa hoặc mạng, hãy ghi tên hoặc ID của nó (ví dụ: db-01).",
  en: "If this is about a server, volume or network, include its name or ID (for example, db-01).",
};

export default function AssistantPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const allowed = !!user?.permissions?.includes(AGENT_USE);
  const cloudCustomer = !!user?.permissions?.includes(INFRA_READ_OWN);
  const agent = useAssistant();
  const endRef = useRef<HTMLDivElement>(null);
  const last = agent.rows.at(-1);
  const lastState = last?.kind === "server" ? last.turn.state : last?.kind;

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [agent.rows.length, lastState, agent.pending.length]);

  if (!user) return null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <main id="main" className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6 md:px-6">
          {!allowed ? (
            <EmptyState icon={Bot} title="The assistant isn't available to you">
              Ask someone on the support team to turn it on for your account.
            </EmptyState>
          ) : agent.rows.length === 0 ? (
            <Welcome name={user.username} onPick={agent.send} />
          ) : (
            <>
              <p className="border-b border-border pb-3 text-xs text-muted-foreground">
                <span className="eyebrow mr-2">Assistant</span>
                Personal details are removed before the assistant reads your message.
              </p>
              {agent.rows.map((row) => (
                <AgentTurnView
                  key={row.key}
                  row={row}
                  pending={agent.pending}
                  handoff={row.kind === "server" && row.turn.handoff_ticket ? agent.handoffs[row.turn.handoff_ticket] : undefined}
                  busyAction={agent.busyAction}
                  actionError={agent.actionError}
                  results={agent.results}
                  creating={agent.creating}
                  createError={agent.createError}
                  onConfirm={agent.confirm}
                  onDismiss={agent.dismiss}
                  onCreateTicket={(id) => void agent.createTicket(id)}
                  onOpenTicket={(id) => void agent.openTicket(id)}
                  onRetry={agent.retry}
                  onAsk={agent.send}
                />
              ))}
              {agent.pendingError && (
                <p role="alert" className="text-sm text-muted-foreground">
                  I couldn&apos;t load the confirmation waiting for you. Retrying…
                </p>
              )}
              {agent.viewingEnded && (
                <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted px-4 py-3 text-sm">
                  This conversation has ended, so it can be read but not added to.
                  <Button size="sm" onClick={() => void agent.startNew()}>
                    <Plus aria-hidden /> Start a new one
                  </Button>
                </div>
              )}
            </>
          )}
          <div ref={endRef} />
        </div>
      </main>
      {allowed && (
        <footer className="border-t border-border bg-card/60">
          <div className="mx-auto max-w-3xl px-4 py-3 md:px-6">
            <Composer
              onSend={agent.send}
              disabled={agent.busy || agent.viewingEnded}
              autoFocus
              minChars={AGENT_MESSAGE_MIN}
              maxChars={AGENT_MESSAGE_MAX}
              note={cloudCustomer ? NAME_THE_RESOURCE[user.language ?? "vi"] : undefined}
            />
            <p className="mt-2 text-xs text-muted-foreground">
              Answers come from approved help pages. The assistant acts only as you, and only after you choose Send.
              Anything it can&apos;t finish goes to a person.
            </p>
          </div>
        </footer>
      )}
    </div>
  );
}
