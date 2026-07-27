"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useRequireAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import TrustSignalsPanel, { type TrustSignalsPanelProps } from "@/components/TrustSignalsPanel";
import ReviewForm, { type ReviewDecisionPayload } from "@/components/ReviewForm";

interface ReviewItemDetail {
  id: number;
  ticket_public_id: string;
  subject_masked: string;
  body_masked: string;
  queue: string;
  priority: number;
  state: string;
  claimed_by: number | null;
  trust_signals: TrustSignalsPanelProps["trustSignals"];
  trust_score: number | null;
  trust_contributions: Record<string, number> | null;
  proposed_draft: { proposed_intent: string; answer_draft?: string; verbatim_quote?: string; kb_slug?: string } | null;
  routing_decisions: TrustSignalsPanelProps["routingDecision"][];
}

export default function ReviewDetailPage() {
  const user = useRequireAuth();
  const params = useParams<{ id: string }>();
  const router = useRouter();

  const [item, setItem] = useState<ReviewItemDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [claiming, setClaiming] = useState(false);

  const load = () => {
    api
      .get<ReviewItemDetail>(`/api/review/items/${params.id}`)
      .then(setItem)
      .catch(() => setError("Failed to load this review item."));
  };

  useEffect(() => {
    if (!user) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, params.id]);

  if (!user) return null;

  const claimItem = async () => {
    setClaiming(true);
    try {
      await api.post(`/api/review/items/${params.id}/claim`);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to claim this item.");
    } finally {
      setClaiming(false);
    }
  };

  const onDecide = async (payload: ReviewDecisionPayload) => {
    setSubmitting(true);
    setError(null);
    try {
      await api.post(`/api/review/items/${params.id}/decide`, payload);
      router.push("/queue");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit the decision.");
    } finally {
      setSubmitting(false);
    }
  };

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!item) return <p className="text-sm text-[var(--text-muted)]">Loading…</p>;

  const proposal = item.proposed_draft;
  const isAutoReply = proposal?.proposed_intent === "auto_reply";

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">{item.ticket_public_id}</h1>
          <p className="text-sm text-[var(--text-muted)]">
            {item.queue} · state: {item.state}
          </p>
        </div>
        {item.state === "pending" && (
          <button
            onClick={claimItem}
            disabled={claiming}
            className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
            style={{ borderColor: "var(--border)" }}
          >
            {claiming ? "Claiming…" : "Claim"}
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="flex flex-col gap-4">
          <div className="card p-4">
            <h2 className="mb-2 text-sm font-semibold">Ticket</h2>
            <p className="text-sm font-medium">{item.subject_masked}</p>
            <p className="mt-1 whitespace-pre-wrap text-sm text-[var(--text-muted)]">{item.body_masked}</p>
          </div>

          {proposal && (
            <div className="card p-4">
              <h2 className="mb-2 text-sm font-semibold">AI proposal ({proposal.proposed_intent})</h2>
              {isAutoReply && (
                <>
                  <p className="text-xs uppercase tracking-wide text-[var(--text-muted)]">KB source</p>
                  <p className="mb-2 text-sm">{proposal.kb_slug}</p>
                  <p className="text-xs uppercase tracking-wide text-[var(--text-muted)]">Verbatim quote</p>
                  <blockquote className="mb-2 border-l-2 pl-2 text-sm italic" style={{ borderColor: "var(--border)" }}>
                    {proposal.verbatim_quote}
                  </blockquote>
                  <p className="text-xs uppercase tracking-wide text-[var(--text-muted)]">Draft answer</p>
                  <p className="whitespace-pre-wrap text-sm">{proposal.answer_draft}</p>
                </>
              )}
              {!isAutoReply && (
                <pre className="overflow-x-auto text-xs text-[var(--text-muted)]">
                  {JSON.stringify(proposal, null, 2)}
                </pre>
              )}
            </div>
          )}

          <ReviewForm hasAutoReplyProposal={isAutoReply} submitting={submitting} onSubmit={onDecide} />
        </div>

        <TrustSignalsPanel
          trustSignals={item.trust_signals}
          trustScore={item.trust_score}
          trustContributions={item.trust_contributions}
          routingDecision={item.routing_decisions[0] ?? null}
        />
      </div>
    </div>
  );
}
