"use client";

// A ticket's comments and the box to add one (F3 · Comment box 10-665): a public reply the
// requester sees, or an internal note; masked before saving. A comment whose masking failed is
// held until a reviewer shows or discards it (UC-F3-03 3y).

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { CommentIn, CommentOut } from "@/lib/types/generated";

type Visibility = "public" | "internal";

interface HeldItem {
  id: string;
  comment: { body_masked: string } | null;
}

export default function CommentsPanel({
  publicId,
  version,
  canWrite,
  canWait,
  onChanged,
}: {
  publicId: string;
  version: number;
  canWrite: boolean;
  canWait: boolean;
  onChanged: () => void;
}) {
  const [comments, setComments] = useState<CommentOut[]>([]);
  const [visibility, setVisibility] = useState<Visibility>("public");
  const [body, setBody] = useState("");
  const [wait, setWait] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setComments(await api.get<CommentOut[]>(`/api/tickets/${encodeURIComponent(publicId)}/comments`));
    } catch {
      setError("Couldn't load the comments.");
    }
  }, [publicId]);

  useEffect(() => {
    void load();
  }, [load]);

  const send = async () => {
    setBusy(true);
    setError(null);
    const payload: CommentIn = {
      body,
      visibility,
      move_to_waiting: visibility === "public" && wait,
      expected_version: version,
    };
    try {
      await api.post<CommentOut>(`/api/tickets/${encodeURIComponent(publicId)}/comments`, payload);
      setBody("");
      setWait(false);
      await load();
      onChanged();
    } catch (err) {
      if (err instanceof ApiError && err.code === "version_conflict") setError("The ticket changed meanwhile. Reload and try again.");
      else if (err instanceof ApiError && err.code === "ticket_in_triage") setError("The ticket is still with triage.");
      else setError(err instanceof ApiError ? err.message : "Couldn't save the comment.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {comments.length === 0 ? (
        <p className="text-sm text-[var(--text-muted)]">No comments yet.</p>
      ) : (
        <ol className="flex flex-col gap-2.5">
          {comments.map((c) => (
            <li key={c.id}>
              <Comment comment={c} onDecided={() => void load().then(onChanged)} />
            </li>
          ))}
        </ol>
      )}

      {canWrite && (
        <div className="rounded-[6px] border border-[var(--border)] p-4">
          <div role="tablist" className="mb-3 flex gap-5 border-b border-[var(--border)] text-sm">
            {(["public", "internal"] as const).map((v) => (
              <button
                key={v}
                role="tab"
                aria-selected={visibility === v}
                onClick={() => setVisibility(v)}
                className={`-mb-px border-b-2 pb-2 ${visibility === v ? "border-[var(--accent)] font-medium text-[var(--accent)]" : "border-transparent text-[var(--text-muted)]"}`}
              >
                {v === "public" ? "Public reply" : "Internal note"}
              </button>
            ))}
          </div>
          <textarea
            className="field min-h-[80px] w-full"
            value={body}
            maxLength={10_000}
            onChange={(e) => setBody(e.target.value)}
            placeholder={visibility === "public" ? "Write to the requester…" : "A note only staff see…"}
          />
          {visibility === "public" && canWait && (
            <label className="mt-2 flex items-center gap-2 text-sm">
              <input type="checkbox" checked={wait} onChange={(e) => setWait(e.target.checked)} />
              Also move to Waiting on requester (pauses SLA)
            </label>
          )}
          {visibility === "public" && body.trim() && (
            <p className="mt-2 rounded-[5px] bg-[var(--surface-2)] px-3 py-2 text-xs text-[var(--text-muted)]">
              Requester sees: &ldquo;{body.trim()}&rdquo;. Masked before saving; placeholders show as [EMAIL_1].
            </p>
          )}
          <div className="mt-3 flex items-center justify-between gap-3">
            <span className="text-xs text-[var(--text-muted)]">
              {visibility === "public" ? "First public reply meets the response clock (BR-F1-06)." : "Never shown to the requester."}
            </span>
            <button className="btn btn-primary" disabled={busy || !body.trim()} onClick={() => void send()}>
              {visibility === "public" ? "Send reply" : "Add note"}
            </button>
          </div>
          {error && <p className="mt-2 text-sm text-[var(--danger)]">{error}</p>}
        </div>
      )}
    </div>
  );
}

function Comment({ comment, onDecided }: { comment: CommentOut; onDecided: () => void }) {
  const [held, setHeld] = useState<HeldItem | null>(null);
  const [busy, setBusy] = useState(false);
  const who = comment.author_kind === "system" ? "System" : comment.author ?? "—";
  const tone =
    comment.visibility === "internal"
      ? "bg-[var(--warn-soft)]"
      : comment.author_kind === "requester"
        ? "bg-[var(--accent-soft)]"
        : "bg-[var(--surface-2)]";

  const decide = async (choice: "show" | "discard") => {
    if (!comment.review_item) return;
    setBusy(true);
    try {
      await api.post(`/api/review/items/${comment.review_item}/comment-decision`, { choice });
      onDecided();
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className={`rounded-[6px] px-3.5 py-2.5 ${tone}`}>
      <p className="text-xs text-[var(--text-muted)]">
        <span className="font-medium text-[var(--text)]">{who}</span> · {comment.author_kind}
        {comment.visibility === "internal" && " · internal note"} · {new Date(comment.created_at).toLocaleString()}
      </p>
      {comment.discarded ? (
        <p className="mt-1 text-sm italic text-[var(--text-muted)]">Discarded after a masking check.</p>
      ) : comment.hidden_for_review ? (
        <div className="mt-1 flex flex-col gap-2 text-sm">
          <p className="italic text-[var(--text-muted)]">Held: masking failed, so a reviewer checks it before anyone reads it.</p>
          {comment.review_item && !held && (
            <button
              className="btn btn-secondary self-start"
              onClick={() => void api.get<HeldItem>(`/api/review/items/${comment.review_item}`).then(setHeld)}
            >
              Review it
            </button>
          )}
          {held && (
            <>
              <p className="whitespace-pre-wrap rounded-[5px] border border-[var(--border)] bg-[var(--surface)] px-3 py-2">
                {held.comment?.body_masked}
              </p>
              <div className="flex gap-2">
                <button className="btn btn-primary" disabled={busy} onClick={() => void decide("show")}>
                  Show to staff
                </button>
                <button className="btn btn-secondary" disabled={busy} onClick={() => void decide("discard")}>
                  Discard
                </button>
              </div>
            </>
          )}
        </div>
      ) : (
        <p className="mt-1 whitespace-pre-wrap break-words text-sm">{comment.body_masked}</p>
      )}
    </article>
  );
}
