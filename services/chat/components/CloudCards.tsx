"use client";

// The cloud's part of an assistant turn (F17): what it looked at in the customer's cloud, and the
// server a change waiting for the customer's Send is about.

import { useEffect, useState } from "react";
import type { AgentActionOut, AgentReceiptOut, ServerDetailOut } from "@/lib/types/generated";
import { infraApi } from "@/lib/api";
import { CLOUD_TOOL_LABEL, SERVER_CHANGE, serverState } from "@/lib/infra";
import { Badge } from "@/components/ui/badge";

const READ_OUTCOME: Record<AgentReceiptOut["outcome"], { label: string; variant: "ok" | "info" | "warn" | "danger" }> = {
  done: { label: "Looked up", variant: "ok" },
  awaiting_confirmation: { label: "Needs your OK", variant: "info" },
  draft_waiting: { label: "Draft waiting", variant: "info" },
  refused: { label: "Not allowed", variant: "warn" },
  failed: { label: "Couldn't look", variant: "danger" },
  unknown: { label: "Not sure", variant: "warn" },
};

/** The cloud reads a turn made, one line each. */
export function CloudReads({ receipts }: { receipts: AgentReceiptOut[] }) {
  return (
    <ul aria-label="What the assistant looked at" className="flex flex-col gap-1.5 border-t border-border pt-3">
      {receipts.map((r, i) => (
        <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
          <Badge variant={READ_OUTCOME[r.outcome].variant}>{READ_OUTCOME[r.outcome].label}</Badge>
          <span>{CLOUD_TOOL_LABEL[r.tool] ?? r.tool}</span>
        </li>
      ))}
    </ul>
  );
}

/** The server a change waiting for the person's Send is about: its name and state, read as the
 * person, and what the change does. */
export function ServerChange({ action }: { action: AgentActionOut }) {
  const [server, setServer] = useState<ServerDetailOut | null>(null);
  const [unread, setUnread] = useState(false);
  useEffect(() => {
    let live = true;
    infraApi
      .server(action.target_ref)
      .then((s) => live && setServer(s))
      .catch(() => live && setUnread(true));
    return () => {
      live = false;
    };
  }, [action.target_ref]);
  return (
    <div className="flex flex-col gap-1 rounded-md bg-muted px-3 py-2 text-sm">
      <p>
        {server ? (
          <>
            <span className="font-medium">{server.name}</span>, {serverState(server.status)} now
          </>
        ) : (
          <span className="num">{action.target_ref}</span>
        )}
      </p>
      {unread && <p className="text-xs text-muted-foreground">I couldn&apos;t load this server&apos;s details just now.</p>}
      {SERVER_CHANGE[action.tool] && <p className="text-xs text-muted-foreground">{SERVER_CHANGE[action.tool]}</p>}
    </div>
  );
}
