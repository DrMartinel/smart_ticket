"use client";

import { useEffect, useRef, useState } from "react";
import { SendIcon } from "./icons";

// Mirrors ChatAskIn.message in core-api (apps/chat/request_schema.py):
// shorter is a 422 there, so it is caught here first.
const MIN_CHARS = 10;
const MAX_CHARS = 10_000;

export default function Composer({
  onSend,
  disabled,
  autoFocus,
}: {
  onSend: (text: string) => void;
  disabled?: boolean;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  const trimmed = text.trim();
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_CHARS;
  const canSend = !disabled && trimmed.length >= MIN_CHARS;

  // Grow with the text, up to a cap; scroll past that.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  const send = () => {
    if (!canSend) return;
    onSend(trimmed);
    setText("");
  };

  return (
    <div className="surface rounded-2xl p-2 transition focus-within:border-[var(--accent)]">
      <div className="flex items-end gap-2">
        <label htmlFor="composer" className="sr-only">
          Describe your problem
        </label>
        <textarea
          id="composer"
          ref={ref}
          rows={1}
          value={text}
          maxLength={MAX_CHARS}
          autoFocus={autoFocus}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Describe what's wrong, e.g. I can't SSH into my EC2 instance…"
          className="max-h-[200px] min-h-[44px] flex-1 resize-none bg-transparent px-3 py-2.5 text-[15px] leading-6 outline-none placeholder:text-[var(--text-muted)]"
        />
        <button
          type="button"
          onClick={send}
          disabled={!canSend}
          aria-label="Send"
          className="brand-gradient grid h-10 w-10 shrink-0 place-items-center rounded-xl text-white transition enabled:hover:brightness-110 disabled:opacity-35"
        >
          <SendIcon />
        </button>
      </div>
      <p className="flex justify-between px-3 pb-1 pt-1 text-xs text-[var(--text-muted)]" aria-live="polite">
        <span>{tooShort ? `A little more detail, please (${MIN_CHARS}+ characters).` : "Enter to send · Shift+Enter for a new line"}</span>
      </p>
    </div>
  );
}
