"use client";

// Reveals one quarantined PII value for a stated reason and hides it again (F5).

import { useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { ApiError, api } from "@/lib/api";
import { piiLevelClasses } from "@/lib/badges";

const REASONS: { code: string; label: string }[] = [
  { code: "verify_identity", label: "verify_identity — Đối chiếu danh tính" },
  { code: "contact_requester", label: "contact_requester — Liên hệ người yêu cầu" },
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
          <button className="btn btn-secondary" onClick={onClose}>
            Hide now
          </button>
        ) : (
          <>
            <button className="btn btn-secondary" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button
              className="btn btn-danger"
              disabled={busy || length < REASON_MIN || length > REASON_MAX}
              onClick={() => void submit()}
            >
              {busy ? "Revealing…" : "Reveal"}
            </button>
          </>
        )
      }
    >
      {revealed ? (
        <div aria-live="polite" className="flex flex-col gap-3">
          <p className="flex items-center gap-2.5">
            <span className={`badge ${piiLevelClasses(level)}`}>{placeholder}</span>
            <span className="font-mono text-base font-semibold">{revealed.value}</span>
          </p>
          <p className="text-xs text-[var(--text-muted)]">
            <span aria-hidden>
              Hides in {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}
            </span>
            {" "}· also hidden when you leave this page. Not copied to logs, notices, exports or the URL.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3.5 text-sm">
          <fieldset>
            <legend className="mb-1.5 text-[11px] uppercase tracking-wide text-[var(--text-muted)]">Reason code</legend>
            <div className="flex flex-col gap-1.5">
              {REASONS.map((r) => (
                <label key={r.code} className="flex items-center gap-1.5 text-xs">
                  <input
                    type="radio"
                    name="reason_code"
                    value={r.code}
                    checked={reasonCode === r.code}
                    onChange={() => setReasonCode(r.code)}
                    className="size-3.5 accent-[var(--accent)]"
                  />
                  {r.label}
                </label>
              ))}
            </div>
          </fieldset>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-[var(--text-muted)]">
              Reason ({REASON_MIN}–{REASON_MAX} chars, masked by regex before saving)
            </span>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              maxLength={REASON_MAX}
              className="rounded-[5px] border border-[var(--border)] bg-[var(--surface)] px-2.5 py-2 text-sm"
            />
          </label>
          {refusal && (
            <p role="alert" className="text-xs text-[var(--danger)]">
              {refusal}
            </p>
          )}
        </div>
      )}
    </Modal>
  );
}
