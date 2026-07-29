"use client";

import { branchClasses } from "@/lib/badges";

interface RoutingDecision {
  branch: string;
  reason_code: string;
  reason_detail: string;
  gate_failed: string | null;
  shadow_mode: boolean;
}

interface TrustSignals {
  retrieval: {
    rerank_top1: number;
    rerank_margin: number;
    bm25_keyword_hit: boolean;
    docs_above_floor: number;
  };
  generation: {
    schema_valid: boolean;
    quote_match_ratio: number;
    quote_source_in_topk: boolean;
    negation_consistent: boolean;
    category_consistent: boolean;
    /** False for proposals with no verbatim quote (route / runbook). */
    quote_applicable?: boolean;
  };
  policy: {
    kb_auto_reply_allowed: boolean;
    kb_risk_tier: string;
    pii_level: string;
    injection_detected: boolean;
    mass_incident: boolean;
  };
}

export interface TrustSignalsPanelProps {
  trustSignals: TrustSignals | null;
  trustScore: number | null;
  trustContributions: Record<string, number> | null;
  routingDecision: RoutingDecision | null;
}

function Bar({ value, max = 1 }: { value: number; max?: number }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-black/10 dark:bg-white/10">
      <div className="h-full rounded-full bg-[var(--accent)]" style={{ width: `${pct}%` }} />
    </div>
  );
}

/**
 * `applicable={false}` renders a neutral "–" instead of a red ✗. Some
 * checks legitimately never run: a route proposal has no verbatim quote
 * to validate, and nothing at all is validated when the AI never ran.
 * Showing those as failures trains reviewers to discount the panel —
 * which defeats the one thing it exists to do.
 */
function BoolChip({ ok, label, applicable = true }: { ok: boolean; label: string; applicable?: boolean }) {
  if (!applicable) {
    return (
      <span className="badge bg-black/5 text-[var(--text-muted)] dark:bg-white/10" title="not applicable to this proposal">
        – {label}
      </span>
    );
  }
  return (
    <span
      className={`badge ${ok ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300" : "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300"}`}
    >
      {ok ? "✓" : "✗"} {label}
    </span>
  );
}

/**
 * Shows WHY a ticket landed where it did — reason code, the specific
 * gate that failed (if any), retrieval/generation signals, and the
 * trust-score contribution breakdown. A bare number teaches a reviewer
 * nothing (spec §4.4); this exists so "why did this only score 0.62" has
 * an answer on screen, not just in a database column.
 */
export default function TrustSignalsPanel({
  trustSignals,
  trustScore,
  trustContributions,
  routingDecision,
}: TrustSignalsPanelProps) {
  if (!trustSignals || !routingDecision) {
    return (
      <div className="card p-4 text-sm text-[var(--text-muted)]">
        No AI run associated with this ticket — routed to review directly (e.g. degraded / mass incident / mask
        failure path).
      </div>
    );
  }

  const { retrieval, generation, policy } = trustSignals;

  // Reason codes that mean the graph stopped before producing any model
  // output. In those runs every generation flag is false because nothing
  // was generated — not because validation rejected something.
  const NO_MODEL_OUTPUT = new Set([
    "embedding_unavailable",
    "ai_engine_unavailable",
    "budget_exceeded",
    "circuit_open",
    "mass_incident",
    "injection_detected",
    "pii_critical",
    "pii_mask_failed",
  ]);
  const aiDidNotRun = NO_MODEL_OUTPUT.has(routingDecision.reason_code);

  // Older rows predate the flag; treat a present quote as the signal.
  const quoteApplicable = generation.quote_applicable ?? generation.quote_match_ratio > 0;

  return (
    <div className="card flex flex-col gap-4 p-4">
      <div className="flex items-center justify-between">
        <div>
          <span className={`badge ${branchClasses(routingDecision.branch)}`}>{routingDecision.branch}</span>
          {routingDecision.shadow_mode && (
            <span className="badge ml-2 bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">
              shadow mode
            </span>
          )}
        </div>
        {trustScore !== null && (
          <div className="text-right">
            <div className="text-2xl font-semibold tabular-nums">{trustScore.toFixed(2)}</div>
            <div className="text-xs text-[var(--text-muted)]">trust score</div>
          </div>
        )}
      </div>

      <div>
        <div className="text-sm font-medium">{routingDecision.reason_code}</div>
        <div className="text-sm text-[var(--text-muted)]">{routingDecision.reason_detail}</div>
        {routingDecision.gate_failed && (
          <div className="mt-1 text-xs text-[var(--text-muted)]">
            gate failed: <code>{routingDecision.gate_failed}</code>
          </div>
        )}
      </div>

      {trustContributions && Object.keys(trustContributions).length > 0 && (
        <div>
          <div className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
            Trust score contributions
          </div>
          <div className="flex flex-col gap-1.5">
            {Object.entries(trustContributions)
              .sort((a, b) => b[1] - a[1])
              .map(([feature, contribution]) => (
                <div key={feature} className="flex items-center gap-2 text-xs">
                  <span className="w-44 shrink-0 truncate text-[var(--text-muted)]">{feature}</span>
                  <span className={`w-14 shrink-0 text-right tabular-nums ${contribution < 0 ? "text-red-500" : ""}`}>
                    {contribution >= 0 ? "+" : ""}
                    {contribution.toFixed(3)}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}

      <div>
        <div className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">Retrieval</div>
        <div className="flex flex-col gap-1.5 text-xs">
          <div className="flex items-center gap-2">
            <span className="w-28 shrink-0 text-[var(--text-muted)]">rerank top1</span>
            <Bar value={retrieval.rerank_top1} />
            <span className="w-10 shrink-0 text-right tabular-nums">{retrieval.rerank_top1.toFixed(2)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-28 shrink-0 text-[var(--text-muted)]">margin (top1-top2)</span>
            <Bar value={retrieval.rerank_margin} />
            <span className="w-10 shrink-0 text-right tabular-nums">{retrieval.rerank_margin.toFixed(2)}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <BoolChip ok={retrieval.bm25_keyword_hit} label="keyword hit" />
            <span className="badge bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">
              {retrieval.docs_above_floor} docs above floor
            </span>
          </div>
        </div>
      </div>

      <div>
        <div className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">Generation</div>
        {aiDidNotRun ? (
          // Every generation check reads false when no model output was
          // ever produced. Rendering four red ✗ implies the model failed
          // validation; it never got that far. Say so instead.
          <div className="text-xs text-[var(--text-muted)]">
            The AI pipeline did not produce a proposal for this ticket
            {routingDecision.reason_code ? ` (${routingDecision.reason_code})` : ""}, so none of the
            generation checks ran. Review the ticket on its own merits.
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            <BoolChip ok={generation.schema_valid} label="schema valid" />
            <BoolChip
              ok={generation.quote_source_in_topk}
              label="quote in top-k"
              applicable={quoteApplicable}
            />
            <BoolChip ok={generation.negation_consistent} label="negation consistent" />
            <BoolChip ok={generation.category_consistent} label="category consistent" />
            {quoteApplicable ? (
              <span className="badge bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">
                quote match {(generation.quote_match_ratio * 100).toFixed(0)}%
              </span>
            ) : (
              <span className="badge bg-black/5 text-[var(--text-muted)] dark:bg-white/10">
                no quote to verify
              </span>
            )}
          </div>
        )}
      </div>

      <div>
        <div className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">Policy</div>
        <div className="flex flex-wrap gap-1.5">
          <BoolChip ok={policy.kb_auto_reply_allowed} label="KB auto-reply allowed" />
          <span className="badge bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">
            risk: {policy.kb_risk_tier}
          </span>
          <span className="badge bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">
            PII: {policy.pii_level}
          </span>
          {policy.injection_detected && <span className="badge bg-red-100 text-red-800">injection detected</span>}
          {policy.mass_incident && <span className="badge bg-orange-100 text-orange-800">mass incident</span>}
        </div>
      </div>
    </div>
  );
}
