"use client";

// The assistant (F15): it can look up and act on the employee's own tickets. Every change it
// proposes waits for the employee's Send; a turn it can't finish goes to a person.

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { Bot, Plus } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useAgentConversation } from "@/lib/agent";
import { AGENT_USE } from "@/lib/session";
import AppHeader from "@/components/AppHeader";
import AgentTurnView from "@/components/AgentTurnView";
import Composer from "@/components/Composer";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/states";

export default function AssistantPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const allowed = !!user?.permissions?.includes(AGENT_USE);
  const agent = useAgentConversation(allowed);
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
    <div className="flex h-dvh flex-col">
      <AppHeader />
      <main id="main" className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6 md:px-6">
          {!allowed ? (
            <EmptyState icon={Bot} title="The assistant isn't available to you">
              You can still ask on the Ask page.
            </EmptyState>
          ) : agent.rows.length === 0 ? (
            <EmptyState icon={Bot} title="Ask the assistant">
              It can open a ticket for you, tell you where a ticket is, and reply to or reopen one of
              yours. It asks before it sends anything.
            </EmptyState>
          ) : (
            <>
              <div className="flex items-center justify-between border-b border-border pb-3">
                <p className="text-xs text-muted-foreground">
                  <span className="eyebrow mr-2">Assistant</span>
                  Personal details are removed before the assistant reads your message.
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void agent.startNew()}
                  disabled={agent.busy}
                  className="-mr-2 text-primary"
                >
                  <Plus aria-hidden /> New conversation
                </Button>
              </div>
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
                  onRetry={agent.retry}
                />
              ))}
            </>
          )}
          <div ref={endRef} />
        </div>
      </main>
      {allowed && (
        <footer className="border-t border-border bg-card/60">
          <div className="mx-auto max-w-3xl px-4 py-3 md:px-6">
            <Composer onSend={agent.send} disabled={agent.busy} autoFocus />
            <p className="mt-2 text-xs text-muted-foreground">
              The assistant acts only as you, and only after you choose Send. Anything it can&apos;t finish goes to a person.
            </p>
          </div>
        </footer>
      )}
    </div>
  );
}
