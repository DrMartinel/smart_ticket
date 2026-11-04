"use client";

import { ArrowRight } from "lucide-react";

// Each one is answered by a page approved for auto-reply in
// demo_kb/curation.json, worded after the golden set's auto-reply tickets
// (g001, g016, g026, g042). A suggestion whose page is not approved can only
// ever end in "Create a ticket"; change this list together with curation.json.
const SUGGESTIONS = [
  "I forgot my AWS access portal password and I'm locked out. How do I reset it?",
  "The AWS VPN Client on my Windows laptop won't connect to the company VPN.",
  "When I ssh to my Linux EC2 instance I get Connection timed out.",
  "Our service gets an error saying it is not authorized to perform lambda:InvokeFunction.",
];

export default function Welcome({ name, onPick }: { name: string; onPick: (text: string) => void }) {
  return (
    <section className="pt-6 sm:pt-12">
      <p className="eyebrow">Signed in as {name}</p>
      <h1 className="mt-2 font-display text-title font-semibold tracking-tight sm:text-display">What&apos;s the problem?</h1>
      <p className="mt-2 max-w-xl text-[15px] leading-6 text-muted-foreground">
        If one of IT&apos;s approved help pages covers it, the answer appears here with the page it came from.
        If not, you can hand it to the support team as a ticket.
      </p>

      <h2 className="eyebrow mt-8">Common requests</h2>
      <ul className="mt-2 divide-y divide-border overflow-hidden rounded-md border border-border bg-card">
        {SUGGESTIONS.map((s) => (
          <li key={s}>
            <button
              onClick={() => onPick(s)}
              className="group flex min-h-11 w-full items-center justify-between gap-4 px-4 py-3 text-left text-[15px] leading-6 transition-colors hover:bg-muted/60 hover:text-primary"
            >
              {s}
              <ArrowRight aria-hidden className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
            </button>
          </li>
        ))}
      </ul>

      <p className="mt-6 text-xs leading-5 text-muted-foreground">
        Names, emails and other personal details are removed before your question is read. Anything the assistant
        isn&apos;t sure about goes to a person.
      </p>
    </section>
  );
}
