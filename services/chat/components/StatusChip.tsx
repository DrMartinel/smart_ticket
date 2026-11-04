// A ticket's status as the requester sees it: waiting on them, resolved, or with the team.

import { cn } from "@/lib/utils";

export function StatusChip({ label, waiting, done, className }: { label: string; waiting: boolean; done: boolean; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-medium",
        waiting ? "bg-warn-soft text-warn" : done ? "bg-ok-soft text-ok" : "bg-primary-soft text-primary",
        className,
      )}
    >
      {label}
    </span>
  );
}
