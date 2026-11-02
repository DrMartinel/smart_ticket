"use client";

import { useEffect, useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

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
    <Card className="transition-colors hover:border-muted-foreground focus-within:border-foreground">
      <label htmlFor="composer" className="sr-only">
        Describe your problem
      </label>
      <Textarea
        id="composer"
        ref={ref}
        rows={2}
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
        placeholder="Describe the problem: what you tried, what happened, any error message."
        className="block max-h-[200px] min-h-[64px] resize-none rounded-none border-0 bg-transparent px-3.5 pt-3 text-[15px] leading-6 shadow-none focus-visible:ring-0 md:text-[15px]"
      />
      <div className="flex items-center justify-between gap-3 border-t border-border px-3.5 py-2">
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {tooShort ? `Add a little more detail (${MIN_CHARS}+ characters).` : "Enter to send, Shift+Enter for a new line"}
        </p>
        <Button type="button" onClick={send} disabled={!canSend} className="py-1.5">
          Send
        </Button>
      </div>
    </Card>
  );
}
