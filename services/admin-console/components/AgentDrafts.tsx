"use client";

// The assistant's drafts on a ticket or its review item (F15, OQ-F15-03 (a)): applied here, by
// the person, with their own session, or dismissed.

import { Bot } from "lucide-react";
import { TOOL_LABEL } from "@/lib/agent";
import { humanize, relativeTime } from "@/lib/format";
import type { AgentActionOut } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";

// Payload fields whose values are codes, shown in words; other values are shown as written.
const CODED = new Set(["action_taken", "kb_verdict", "category_verdict", "corrected_category", "priority", "decision"]);
const HIDDEN = new Set(["time_spent_sec", "expected_version"]);

export default function AgentDrafts({
  drafts,
  busy,
  version,
  canDecide,
  onUse,
  onApply,
  onDismiss,
}: {
  drafts: AgentActionOut[];
  busy: boolean;
  // The ticket's version now; a draft made at another one would be refused.
  version: number;
  // Whether this decision draft's review form is open to this person (they hold the claim).
  canDecide: (draft: AgentActionOut) => boolean;
  onUse: (draft: AgentActionOut) => void;
  onApply: (draft: AgentActionOut) => void;
  onDismiss: (draft: AgentActionOut) => void;
}) {
  if (drafts.length === 0) return null;
  return (
    <div className="flex flex-col gap-3">
      {drafts.map((d) => {
        const payload = (d.arguments.payload ?? {}) as Record<string, unknown>;
        const fields = Object.entries(payload).filter(([k, v]) => v !== null && v !== "" && !HIDDEN.has(k));
        const stale = typeof payload.expected_version === "number" && payload.expected_version !== version;
        const decision = d.tool === "draft_review_decision";
        return (
          <section
            key={d.action_id}
            aria-label="Draft from the assistant"
            className="flex flex-col gap-2 rounded-md border border-dashed border-proposal/50 bg-proposal-soft/40 px-4 py-3 text-sm"
          >
            <p className="flex items-center gap-2 font-medium">
              <Bot className="size-4" aria-hidden />
              Draft from the assistant: {TOOL_LABEL[d.tool] ?? d.tool}
              <span className="font-normal text-muted-foreground">· {relativeTime(d.created_at)}</span>
            </p>
            {fields.length > 0 && (
              <dl className="grid grid-cols-[140px_minmax(0,1fr)] gap-x-3 gap-y-1">
                {fields.map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-muted-foreground">{humanize(k)}</dt>
                    <dd className="whitespace-pre-wrap">
                      {typeof v === "string" ? (CODED.has(k) ? humanize(v) : v) : JSON.stringify(v)}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
            <p className="text-xs text-muted-foreground">
              Nothing has changed. Check the evidence on this page; the decision is yours.
            </p>
            {stale && (
              <p className="text-xs text-warn">
                The ticket changed since this was drafted, so it can&apos;t be applied. Dismiss it or ask again.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              {decision ? (
                <Button size="sm" variant="outline" disabled={busy || !canDecide(d)} onClick={() => onUse(d)}>
                  {canDecide(d) ? "Open in the review form" : "Claim the review to use it"}
                </Button>
              ) : (
                <Button size="sm" variant="outline" disabled={busy || stale} onClick={() => onApply(d)}>
                  Apply
                </Button>
              )}
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => onDismiss(d)}>
                Dismiss
              </Button>
            </div>
          </section>
        );
      })}
    </div>
  );
}
