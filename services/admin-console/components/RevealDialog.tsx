"use client";

// Reveals one quarantined PII value for a stated reason and hides it again (F5).

import { useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { ApiError, api } from "@/lib/api";
import { piiLevelTone } from "@/lib/badges";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";

const REASONS: { code: string; label: string }[] = [
  { code: "verify_identity", label: "Verify the requester's identity" },
  { code: "contact_requester", label: "Contact the requester" },
  { code: "security_investigation", label: "security_investigation" },
  { code: "legal_request", label: "legal_request" },
];
const REASON_MIN = 10;
const REASON_MAX = 500;

interface Revealed {
  placeholder: string;
  value: string;
  shown_until: string;
}

export default function RevealDialog({
  publicId,
  placeholder,
  level,
  onClose,
}: {
  publicId: string;
  placeholder: string;
  level: string;
  onClose: () => void;
}) {
  const [reasonCode, setReasonCode] = useState(REASONS[0].code);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<Revealed | null>(null);
  const [left, setLeft] = useState(0);

  useEffect(() => {
    if (!revealed) return;
    const until = new Date(revealed.shown_until).getTime();
    const tick = () => {
      const seconds = Math.ceil((until - Date.now()) / 1000);
      if (seconds <= 0) {
        setRevealed(null);
        onClose();
      } else {
        setLeft(seconds);
      }
    };
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [revealed, onClose]);

  const submit = async () => {
    setBusy(true);
    setRefusal(null);
    try {
      setRevealed(
        await api.post<Revealed>(`/api/tickets/${encodeURIComponent(publicId)}/quarantine/reveal`, {
          placeholder,
          reason_code: reasonCode,
          reason,
        }),
      );
    } catch (err) {
      setRefusal(err instanceof ApiError ? `${err.code ?? err.status}: ${err.message}` : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const length = reason.trim().length;

  return (
    <Modal
      open
      title={`Reveal ${placeholder}`}
      subtitle="Your name, the reason and the time go to the PII access log before the value is decrypted. Security can see every reveal."
      onClose={onClose}
      width="max-w-[520px]"
      footer={
        revealed ? (
          <Button variant="outline" onClick={onClose}>
            Hide now
          </Button>
        ) : (
          <>
            <Button variant="outline" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button variant="destructive"
              disabled={busy || length < REASON_MIN || length > REASON_MAX}
              onClick={() => void submit()}
            >
              {busy ? "Revealing…" : "Reveal"}
            </Button>
          </>
        )
      }
    >
      {revealed ? (
        <div aria-live="polite" className="flex flex-col gap-3">
          <p className="flex items-center gap-2.5">
            <Badge variant={piiLevelTone(level)}>{placeholder}</Badge>
            <span className="font-mono text-base font-semibold">{revealed.value}</span>
          </p>
          <p className="text-xs text-muted-foreground">
            <span aria-hidden>
              Hides in {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}
            </span>
            {" "}· also hidden when you leave this page. Not copied to logs, notices, exports or the URL.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3.5 text-sm">
          <fieldset>
            <legend className="mb-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">Reason code</legend>
            <RadioGroup value={reasonCode} onValueChange={(next) => setReasonCode(next as typeof reasonCode)} className="gap-2">
              {REASONS.map((r) => (
                <label key={r.code} className="flex items-center gap-2 text-xs">
                  <RadioGroupItem value={r.code} />
                  {r.label}
                </label>
              ))}
            </RadioGroup>
          </fieldset>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-muted-foreground">
              Reason ({REASON_MIN}–{REASON_MAX} chars, masked by regex before saving)
            </span>
            <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={REASON_MAX} />
          </label>
          {refusal && (
            <p role="alert" className="text-xs text-danger">
              {refusal}
            </p>
          )}
        </div>
      )}
    </Modal>
  );
}
