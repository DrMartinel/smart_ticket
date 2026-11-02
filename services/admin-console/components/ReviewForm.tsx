"use client";

import { useEffect, useRef, useState } from "react";
import { NativeSelect } from "@/components/ui/native-select";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

export interface ReviewDecisionPayload {
  action_taken: "approve" | "edit_and_send" | "reject" | "reroute" | "escalate";
  kb_verdict: "correct" | "wrong" | "partial" | "not_applicable" | null;
  category_verdict: "correct" | "wrong" | null;
  corrected_category: string | null;
  corrected_kb_id: string | null;
  override_reason: string | null;
  time_spent_sec: number;
}

const CATEGORIES = ["hardware", "software", "network", "access", "security", "other"];

const ACTIONS: { value: ReviewDecisionPayload["action_taken"]; label: string; hint: string }[] = [
  { value: "approve", label: "Approve", hint: "Carry out what the AI proposed." },
  { value: "edit_and_send", label: "Edit and send", hint: "The answer is close; you'll correct it." },
  { value: "reroute", label: "Reroute", hint: "It belongs to a different team." },
  { value: "escalate", label: "Escalate", hint: "Needs a more senior person." },
  { value: "reject", label: "Reject", hint: "The proposal is wrong; handle it manually." },
];

const KB_VERDICTS: { value: NonNullable<ReviewDecisionPayload["kb_verdict"]>; label: string }[] = [
  { value: "correct", label: "Yes" },
  { value: "partial", label: "Partly" },
  { value: "wrong", label: "No" },
  { value: "not_applicable", label: "Can't tell" },
];

/**
 * Spec §3.4 / §12.4: specific questions, not a single Approve button —
 * this is what turns a human decision into a training label instead of a
 * rubber stamp. `time_spent_sec` is tracked automatically (not
 * self-reported) so §11.1's "median_time_spent_per_review < 10s = not
 * reading" metric measures something real.
 */
export default function ReviewForm({
  hasAutoReplyProposal,
  aiCategory,
  submitting,
  onSubmit,
}: {
  hasAutoReplyProposal: boolean;
  aiCategory: string | null;
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
      setError("Say why: anything but Approve needs a reason, and it becomes a training example.");
      return;
    }
    if (categoryVerdict === "wrong" && !correctedCategory) {
      setError("Pick the right category.");
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
    <form onSubmit={submit} className="flex flex-col gap-5">
      {hasAutoReplyProposal && (
        <Question legend="Does the cited help page answer this ticket?">
          <Segmented options={KB_VERDICTS} value={kbVerdict} onChange={setKbVerdict} />
        </Question>
      )}

      <Question legend={aiCategory ? `Is "${aiCategory}" the right category?` : "Is the category right?"}>
        <Segmented
          options={[
            { value: "correct", label: "Yes" },
            { value: "wrong", label: "No" },
          ]}
          value={categoryVerdict}
          onChange={setCategoryVerdict}
        />
        {categoryVerdict === "wrong" && (
          <NativeSelect wrapperClassName="mt-2 w-56"
            value={correctedCategory}
            onChange={(e) => setCorrectedCategory(e.target.value)}
            aria-label="Correct category"
          >
            <option value="">Choose the right category…</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </NativeSelect>
        )}
      </Question>

      <Question legend="What should happen?">
        <RadioGroup value={action} onValueChange={(next) => setAction(next as ReviewDecisionPayload["action_taken"])} className="gap-1.5">
          {ACTIONS.map((a) => (
            <label
              key={a.value}
              className={`flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2 text-sm ${
                action === a.value ? "border-primary bg-primary-soft" : "border-border"
              }`}
            >
              <RadioGroupItem value={a.value} className="mt-0.5" />
              <span>
                <span className="font-medium">{a.label}</span>
                <span className="block text-xs text-muted-foreground">{a.hint}</span>
              </span>
            </label>
          ))}
        </RadioGroup>
      </Question>

      {requiresReason && (
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Why?
          <Textarea
            className="font-normal"
            rows={3}
            value={overrideReason}
            onChange={(e) => setOverrideReason(e.target.value)}
            placeholder="What is wrong or missing in the AI's proposal? This becomes a training example."
          />
        </label>
      )}

      {error && <p className="text-sm text-danger">{error}</p>}

      <Button type="submit" disabled={submitting} className="self-start">
        {submitting ? "Saving…" : "Submit review"}
      </Button>
    </form>
  );
}

function Question({ legend, children }: { legend: string; children: React.ReactNode }) {
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-medium">{legend}</legend>
      {children}
    </fieldset>
  );
}

function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T | null;
  onChange: (value: T) => void;
}) {
  return (
    <ToggleGroup type="single" variant="outline" value={value ?? ""} onValueChange={(next) => next && onChange(next as T)}>
      {options.map((o) => (
        <ToggleGroupItem
          key={o.value}
          value={o.value}
          className="px-3.5 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
        >
          {o.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
