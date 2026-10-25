// Renders an answer's light Markdown (paragraphs, numbered and bulleted
// lists, **bold**, `code`) as React elements. Nothing is injected as HTML,
// so text from the model can never become markup.

import type { ReactNode } from "react";

type Block = { kind: "p"; text: string } | { kind: "ol" | "ul"; items: string[] };

const NUMBERED = /^\s*\d{1,2}[.)]\s+/;
const BULLETED = /^\s*[-*•]\s+/;

export default function AnswerText({ text }: { text: string }) {
  const blocks = text.includes("\n") ? parseBlocks(text) : (splitInlineSteps(text) ?? [{ kind: "p", text } as Block]);
  return (
    <div className="answer flex flex-col gap-2.5 break-words">
      {blocks.map((block, i) => {
        if (block.kind === "p") return <p key={i}>{inline(block.text)}</p>;
        const List = block.kind;
        return (
          <List
            key={i}
            className={`${block.kind === "ol" ? "list-decimal" : "list-disc"} space-y-1.5 pl-5 marker:text-[var(--text-muted)]`}
          >
            {block.items.map((item, j) => (
              <li key={j} className="pl-1">
                {inline(item)}
              </li>
            ))}
          </List>
        );
      })}
    </div>
  );
}

function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length) blocks.push({ kind: "p", text: paragraph.join(" ") });
    paragraph = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const kind = NUMBERED.test(line) ? "ol" : BULLETED.test(line) ? "ul" : null;
    if (!line) {
      flush();
    } else if (kind) {
      flush();
      const item = line.replace(kind === "ol" ? NUMBERED : BULLETED, "");
      const last = blocks.at(-1);
      if (last && last.kind === kind) last.items.push(item);
      else blocks.push({ kind, items: [item] });
    } else {
      const last = blocks.at(-1);
      // A wrapped line right after a list item continues that item.
      if (!paragraph.length && last && last.kind !== "p" && raw.startsWith(" ")) {
        last.items[last.items.length - 1] += ` ${line}`;
      } else {
        paragraph.push(line);
      }
    }
  }
  flush();
  return blocks;
}

// The model sometimes writes steps inline ("…these steps: 1. Do this. 2. Do
// that."). Only markers numbered 1, 2, 3… in order count, so a stray
// "Windows 10. " never splits the text; fewer than two leaves it as written.
// Whatever follows the last step's first sentence is a closing paragraph.
function splitInlineSteps(text: string): Block[] | null {
  const marks: { start: number; end: number }[] = [];
  const marker = /(?:^|\s)(\d{1,2})\.\s+/g;
  for (let m = marker.exec(text); m; m = marker.exec(text)) {
    if (Number(m[1]) === marks.length + 1) marks.push({ start: m.index, end: m.index + m[0].length });
  }
  if (marks.length < 2) return null;

  const steps = marks.map((mk, i) => text.slice(mk.end, marks[i + 1]?.start ?? text.length).trim());
  const last = steps[steps.length - 1].match(/^(.*?[.!?])\s+([A-Z][\s\S]*)$/);
  let outro = "";
  if (last) {
    steps[steps.length - 1] = last[1];
    outro = last[2];
  }
  const intro = text.slice(0, marks[0].start).trim();
  return [
    ...(intro ? [{ kind: "p", text: intro } as Block] : []),
    { kind: "ol", items: steps },
    ...(outro ? [{ kind: "p", text: outro } as Block] : []),
  ];
}

/** One line of text with its **bold** and `code` rendered. */
export function InlineText({ text }: { text: string }) {
  return <>{inline(text)}</>;
}

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const token = /\*\*(.+?)\*\*|`([^`]+)`/g;
  let at = 0;
  for (let m = token.exec(text); m; m = token.exec(text)) {
    if (m.index > at) out.push(text.slice(at, m.index));
    out.push(m[1] !== undefined ? <strong key={m.index}>{m[1]}</strong> : <code key={m.index}>{m[2]}</code>);
    at = m.index + m[0].length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}
