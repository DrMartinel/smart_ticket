"use client";

// Masked ticket text with each PII placeholder as a chip; a chip opens the reveal dialog (F5).

import { Fragment, useState } from "react";
import RevealDialog from "@/components/RevealDialog";
import { piiLevelTone } from "@/lib/badges";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const PLACEHOLDER = /(\[[A-Z_]+_\d+\])/g;

export interface PlaceholderLevel {
  placeholder: string;
  level: string;
}

export default function PiiText({
  publicId,
  text,
  placeholders,
  canReveal,
  isSecurity,
}: {
  publicId: string;
  text: string;
  placeholders: PlaceholderLevel[];
  canReveal: boolean;
  isSecurity: boolean;
}) {
  const [target, setTarget] = useState<PlaceholderLevel | null>(null);
  const levels = new Map(placeholders.map((p) => [p.placeholder, p.level]));

  return (
    <>
      {text.split(PLACEHOLDER).map((part, i) => {
        const level = levels.get(part);
        if (!level) return <Fragment key={i}>{part}</Fragment>;
        const securityOnly = level === "critical" && !isSecurity;
        const label = securityOnly ? `${part} · security only` : part;
        if (!canReveal || securityOnly) {
          return (
            <Badge variant={piiLevelTone(level)} key={i} title={securityOnly ? "Only security can reveal a credential" : undefined}>
              {label}
            </Badge>
          );
        }
        return (
          <Badge asChild variant={piiLevelTone(level)} key={i}>
            <Button variant="link" size="inline"
              type="button"
              onClick={() => setTarget({ placeholder: part, level })}
              className="cursor-pointer underline-offset-2"
              aria-label={`Reveal ${part}`}
            >
              {label}
            </Button>
          </Badge>
        );
      })}
      {target && (
        <RevealDialog
          publicId={publicId}
          placeholder={target.placeholder}
          level={target.level}
          onClose={() => setTarget(null)}
        />
      )}
    </>
  );
}
