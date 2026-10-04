"use client";

import { BookIcon, ShieldIcon, SparkleIcon, TicketIcon } from "./icons";

// Questions the demo KB (AWS documentation, demo_kb/) can speak to.
const SUGGESTIONS = [
  "I can't connect to my EC2 instance over SSH, the connection times out.",
  "How do I reset the MFA device on my IAM user?",
  "How can I give a teammate read-only access to one S3 bucket?",
  "My Lambda function times out when it calls an external API.",
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
