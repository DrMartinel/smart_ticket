"use client";

// The person's earlier assistant conversations in the sidebar, newest first: pick one to read it,
// or to carry on with it while it is still active.

import type { AgentConversationSummaryOut } from "@/lib/types/generated";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export default function ConversationHistory({
  history,
  error,
  currentId,
  onOpen,
}: {
  history: AgentConversationSummaryOut[];
  error: boolean;
  currentId: string | null;
  onOpen: (id: string) => void;
}) {
  if (error) {
    return (
      <p role="alert" className="px-2 text-xs text-muted-foreground">
        I couldn&apos;t load your earlier conversations.
      </p>
    );
  }
  if (history.length === 0) return null;
  return (
    <section aria-label="Recents" className="flex min-h-0 flex-col gap-1">
      <h2 className="eyebrow px-2">Recents</h2>
      <ul className="flex min-h-0 flex-col gap-0.5 overflow-y-auto">
        {history.map((c) => (
          <li key={c.conversation_id}>
            <button
              onClick={() => onOpen(c.conversation_id)}
              aria-current={c.conversation_id === currentId ? "true" : undefined}
              className={cn(
                "flex min-h-9 w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted",
                c.conversation_id === currentId ? "bg-primary-soft text-primary" : "text-foreground",
              )}
            >
              <span className="min-w-0 flex-1 truncate">{c.first_message || "Conversation"}</span>
              {c.state === "ended" && <Badge variant="neutral">Ended</Badge>}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
