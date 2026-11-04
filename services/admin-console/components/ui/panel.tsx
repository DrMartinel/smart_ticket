// A page's bordered section with a small heading, and the block that marks what a model proposed.

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Panel({
  title,
  aside,
  children,
  className,
  bodyClassName,
  flush = false,
  ...rest
}: {
  title?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  /** Content runs edge to edge (tables, lists). */
  flush?: boolean;
} & Omit<React.ComponentProps<"section">, "title">) {
  return (
    <section className={cn("min-w-0 rounded-md border border-border bg-card text-card-foreground", className)} {...rest}>
      {(title || aside) && (
        <div className={cn("flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 pt-3 sm:px-5", flush ? "border-b border-border pb-3" : "pb-0")}>
          {title && <h2 className="eyebrow text-foreground/80">{title}</h2>}
          {aside && <div className="flex flex-wrap items-center gap-2 text-sm">{aside}</div>}
        </div>
      )}
      <div className={cn(flush ? "" : "px-4 pt-3 pb-4 sm:px-5 sm:pb-5", bodyClassName)}>{children}</div>
    </section>
  );
}

/** Content a model wrote: a dashed ochre rule and an "AI proposal" tag. */
export function Proposal({ label = "AI proposal", children, className }: { label?: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-r-md border-l-2 border-dashed border-proposal bg-proposal-soft/60 py-3 pr-3 pl-4", className)}>
      <p className="eyebrow mb-1.5 !text-proposal">{label}</p>
      <div className="text-sm">{children}</div>
    </div>
  );
}

/** A decision a person or a rule made: a solid Forest rule. */
export function Decision({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-r-md border-l-2 border-primary bg-primary-soft/50 py-3 pr-3 pl-4", className)}>
      <p className="eyebrow mb-1.5 !text-primary">{label}</p>
      <div className="text-sm">{children}</div>
    </div>
  );
}

/** A two-column list of facts: a muted term and its value. */
export function Facts({ children, className, termWidth = "110px" }: { children: ReactNode; className?: string; termWidth?: string }) {
  return (
    <dl className={cn("grid gap-x-4 gap-y-2 text-sm", className)} style={{ gridTemplateColumns: `${termWidth} minmax(0,1fr)` }}>
      {children}
    </dl>
  );
}
