"use client";

import { BookIcon, ShieldIcon, SparkleIcon, TicketIcon } from "./icons";

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
    <div className="turn-in mx-auto flex max-w-2xl flex-col items-center pt-10 text-center sm:pt-16">
      <div className="brand-gradient grid h-14 w-14 place-items-center rounded-2xl text-white shadow-lg">
        <SparkleIcon className="h-7 w-7" />
      </div>
      <h1 className="mt-5 text-2xl font-semibold tracking-tight sm:text-3xl">Hi {name}, what can I help with?</h1>
      <p className="mt-2 max-w-md text-[15px] text-[var(--text-muted)]">
        Describe the problem. If an approved help page answers it, you&apos;ll get the answer here. If not, I&apos;ll
        offer to open a ticket for you.
      </p>

      <div className="mt-8 grid w-full gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onPick(s)}
            className="surface rounded-xl px-4 py-3 text-left text-sm transition hover:-translate-y-0.5 hover:border-[var(--accent)]"
          >
            {s}
          </button>
        ))}
      </div>

      <ul className="mt-8 flex flex-wrap justify-center gap-x-5 gap-y-2 text-xs text-[var(--text-muted)]">
        <li className="flex items-center gap-1.5">
          <ShieldIcon /> Personal details hidden first
        </li>
        <li className="flex items-center gap-1.5">
          <BookIcon className="h-3.5 w-3.5" /> Answers only from approved pages
        </li>
        <li className="flex items-center gap-1.5">
          <TicketIcon className="h-3.5 w-3.5" /> A person when it&apos;s unsure
        </li>
      </ul>
    </div>
  );
}
