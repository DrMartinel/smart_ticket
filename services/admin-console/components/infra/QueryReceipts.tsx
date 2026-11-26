"use client";

// An assistant turn's infra queries, each with its link to Prometheus or Kibana, and the warnings
// core-api wrote for the sources the turn could not read (F17 BR-F17-07, BR-F17-10).

import { AlertTriangle, ExternalLink } from "lucide-react";
import { BACKEND_LABEL, CHECK_TEXT, QUERY_KIND_LABEL, QUERY_OUTCOME } from "@/lib/infra";
import type { InfraQueryReceiptOut } from "@/lib/types/generated";
import { Badge } from "@/components/ui/badge";

export default function QueryReceipts({ queries, warnings }: { queries: InfraQueryReceiptOut[]; warnings: string[] }) {
  if (queries.length === 0 && warnings.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      {warnings.length > 0 && (
        <ul aria-label="Missing from this answer" className="flex flex-col gap-1 rounded-md bg-warn-soft px-3 py-2 text-warn">
          {warnings.map((w) => (
            <li key={w} className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}
      {queries.length > 0 && (
        <ul aria-label="What the assistant looked at" className="flex flex-col gap-1.5 border-t border-border pt-2">
          {queries.map((q) => (
            <QueryReceipt key={q.id} query={q} />
          ))}
        </ul>
      )}
    </div>
  );
}

function QueryReceipt({ query }: { query: InfraQueryReceiptOut }) {
  const outcome = QUERY_OUTCOME[query.outcome];
  const notes: string[] = [];
  if (query.outcome === "ok") notes.push(`${query.rows} ${query.rows === 1 ? "result" : "results"}`);
  if (query.truncated) notes.push("cut to the size limit, so some results are missing");
  if (query.withheld > 0) notes.push(`${query.withheld} ${query.withheld === 1 ? "text" : "texts"} withheld`);
  if (query.outcome === "backend_unavailable") notes.push(`${BACKEND_LABEL[query.failed_backend ?? query.backend]} didn't answer`);
  return (
    <li className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={outcome.tone}>{outcome.label}</Badge>
        <span>
          {BACKEND_LABEL[query.backend]} {QUERY_KIND_LABEL[query.kind]}
        </span>
        {query.link && (
          <a href={query.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
            Open the query
            <ExternalLink className="size-3" aria-hidden />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        )}
      </div>
      {notes.length > 0 && <p className="text-xs text-muted-foreground">{notes.join(" · ")}</p>}
      {query.outcome === "refused" && (
        <p className="text-xs text-warn">
          {query.refusal_reason ? CHECK_TEXT[query.refusal_reason] : query.refusal === "infra_not_found" ? "No such resource." : "Refused."}
        </p>
      )}
      {query.compiled && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">What was sent</summary>
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted px-2 py-1.5 font-mono text-[11px]">{query.compiled}</pre>
        </details>
      )}
    </li>
  );
}
