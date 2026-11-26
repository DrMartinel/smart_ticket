"use client";

// The cloud's part of an assistant turn (F17): the receipt of each query it ran in the customer's
// cloud with the warnings core-api wrote for the sources it couldn't read, and the server a change
// waiting for the customer's Send is about.

import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import type { AgentActionOut, InfraQueryReceiptOut, Language, ServerDetailOut } from "@/lib/types/generated";
import { infraApi } from "@/lib/api";
import { QUERY_TONE, RECEIPT_WORDS, SERVER_CHANGE, serverState } from "@/lib/infra";
import { Badge } from "@/components/ui/badge";

/** The turn's warnings, then one line per query it ran. */
export function QueryReceipts({
  queries,
  warnings,
  language,
}: {
  queries: InfraQueryReceiptOut[];
  warnings: string[];
  language: Language;
}) {
  const words = RECEIPT_WORDS[language];
  if (queries.length === 0 && warnings.length === 0) return null;
  return (
    <div className="flex flex-col gap-2 border-t border-border pt-3 text-sm">
      {warnings.length > 0 && (
        <ul aria-label={words.missing} className="flex flex-col gap-1 rounded-md bg-warn-soft px-3 py-2 text-warn">
          {warnings.map((w) => (
            <li key={w} className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}
      {queries.length > 0 && (
        <ul aria-label={words.heading} className="flex flex-col gap-1.5">
          {queries.map((q) => (
            <QueryReceipt key={q.id} query={q} language={language} />
          ))}
        </ul>
      )}
    </div>
  );
}

function QueryReceipt({ query, language }: { query: InfraQueryReceiptOut; language: Language }) {
  const words = RECEIPT_WORDS[language];
  const notes: string[] = [];
  if (query.outcome === "ok") notes.push(words.results(query.rows));
  if (query.truncated) notes.push(words.cut);
  if (query.outcome === "backend_unavailable") notes.push(words.noAnswer(words.source[query.failed_backend ?? query.backend]));
  return (
    <li className="flex flex-col gap-0.5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={QUERY_TONE[query.outcome]}>{words.outcome[query.outcome]}</Badge>
        <span>{words.looked[query.backend]}</span>
      </div>
      {notes.length > 0 && <p className="text-xs text-muted-foreground">{notes.join(" · ")}</p>}
      {query.outcome === "refused" && (
        <p className="text-xs text-warn">
          {query.refusal_reason
            ? words.check[query.refusal_reason]
            : query.refusal === "infra_not_found"
              ? words.notFound
              : words.refused}
        </p>
      )}
    </li>
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
