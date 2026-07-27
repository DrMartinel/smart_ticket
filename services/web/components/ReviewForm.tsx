"use client";

import { useEffect, useRef, useState } from "react";

export interface ReviewDecisionPayload {
  action_taken: "approve" | "edit_and_send" | "reject" | "reroute" | "escalate";
  kb_verdict: "correct" | "wrong" | "partial" | "not_applicable" | null;
  category_verdict: "correct" | "wrong" | null;
  corrected_category: string | null;
  corrected_kb_id: number | null;
  override_reason: string | null;
  time_spent_sec: number;
}

const CATEGORIES = ["hardware", "software", "network", "access", "security", "other"];

/**
 * Spec §3.4 / §12.4: specific questions, not a single Approve button —
 * this is what turns a human decision into a training label instead of a
 * rubber stamp. `time_spent_sec` is tracked automatically (not
 * self-reported) so §11.1's "median_time_spent_per_review < 10s = not
 * reading" metric measures something real.
 */
export default function ReviewForm({
  hasAutoReplyProposal,
  submitting,
  onSubmit,
}: {
  hasAutoReplyProposal: boolean;
  submitting: boolean;
  onSubmit: (payload: ReviewDecisionPayload) => void;
}) {
  const startedAt = useRef(Date.now());
  const [kbVerdict, setKbVerdict] = useState<ReviewDecisionPayload["kb_verdict"]>(null);
  const [categoryVerdict, setCategoryVerdict] = useState<ReviewDecisionPayload["category_verdict"]>(null);
  const [correctedCategory, setCorrectedCategory] = useState("");
  const [action, setAction] = useState<ReviewDecisionPayload["action_taken"]>("approve");
  const [overrideReason, setOverrideReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    startedAt.current = Date.now();
  }, []);

  const requiresReason = action !== "approve";

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (requiresReason && !overrideReason.trim()) {
      setError("A reason is required for any action other than Approve.");
      return;
    }
    onSubmit({
      action_taken: action,
      kb_verdict: hasAutoReplyProposal ? kbVerdict : null,
      category_verdict: categoryVerdict,
      corrected_category: categoryVerdict === "wrong" ? correctedCategory || null : null,
      corrected_kb_id: null,
      override_reason: requiresReason ? overrideReason.trim() : null,
      time_spent_sec: Math.round((Date.now() - startedAt.current) / 1000),
    });
  };

  return (
    <form onSubmit={submit} className="card flex flex-col gap-5 p-4">
      <h2 className="text-sm font-semibold">Review decision</h2>

      {hasAutoReplyProposal && (
        <fieldset>
          <legend className="mb-2 text-sm font-medium">Is the cited KB article correct for this ticket?</legend>
          <div className="flex flex-wrap gap-3 text-sm">
            {(["correct", "wrong", "partial", "not_applicable"] as const).map((v) => (
              <label key={v} className="flex items-center gap-1.5">
                <input type="radio" name="kb_verdict" checked={kbVerdict === v} onChange={() => setKbVerdict(v)} />
                {v.replace("_", " ")}
              </label>
            ))}
          </div>
        </fieldset>
      )}

      <fieldset>
        <legend className="mb-2 text-sm font-medium">Is the category correct?</legend>
        <div className="flex flex-wrap gap-3 text-sm">
          {(["correct", "wrong"] as const).map((v) => (
            <label key={v} className="flex items-center gap-1.5">
              <input
                type="radio"
                name="category_verdict"
                checked={categoryVerdict === v}
                onChange={() => setCategoryVerdict(v)}
              />
              {v}
            </label>
          ))}
        </div>
        {categoryVerdict === "wrong" && (
          <select
            className="mt-2 rounded border px-2 py-1 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--bg)" }}
            value={correctedCategory}
            onChange={(e) => setCorrectedCategory(e.target.value)}
          >
            <option value="">Correct category…</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        )}
      </fieldset>

      <fieldset>
        <legend className="mb-2 text-sm font-medium">What should happen to this ticket?</legend>
        <select
          className="rounded border px-2 py-1.5 text-sm"
          style={{ borderColor: "var(--border)", background: "var(--bg)" }}
          value={action}
          onChange={(e) => setAction(e.target.value as ReviewDecisionPayload["action_taken"])}
        >
          <option value="approve">Approve — send/route as proposed</option>
          <option value="edit_and_send">Edit and send</option>
          <option value="reject">Reject</option>
          <option value="reroute">Reroute to a different team</option>
          <option value="escalate">Escalate</option>
        </select>
      </fieldset>

      {requiresReason && (
        <label className="text-sm">
          Reason for override <span className="text-red-500">*</span>
          <textarea
            className="mt-1 w-full rounded border px-3 py-2 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--bg)" }}
            rows={3}
            value={overrideReason}
            onChange={(e) => setOverrideReason(e.target.value)}
            placeholder="Why is the AI's proposal wrong or incomplete? This becomes a training label."
          />
        </label>
      )}

      {error && <p className="text-sm text-red-600">{error}</p>}

      <button
        type="submit"
        disabled={submitting}
        className="self-start rounded bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {submitting ? "Submitting…" : "Submit decision"}
      </button>
    </form>
  );
}
