// The ledger header every page opens with: where you are, the title, what the page is for, its actions.

import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
import { cn } from "@/lib/utils";

export function PageHeader({
  eyebrow,
  vi,
  title,
  description,
  actions,
  back,
  meta,
  className,
}: {
  /** Where the page sits, e.g. "Workspace / Tickets". */
  eyebrow?: string;
  /** The section's Vietnamese name, shown beside the eyebrow. */
  vi?: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  back?: { href: string; label: string };
  /** A line of facts under the title (ID, status, dates). */
  meta?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("mb-6 border-b border-border pb-5", className)}>
      {back && (
        <Link
          href={back.href}
          className="mb-3 inline-flex min-h-8 items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-4" aria-hidden />
          {back.label}
        </Link>
      )}
      {(eyebrow || vi) && (
        <p className="mb-1.5 flex flex-wrap items-baseline gap-x-2">
          {eyebrow && <span className="eyebrow">{eyebrow}</span>}
          {vi && <span lang="vi" className="text-xs italic text-muted-foreground">{vi}</span>}
        </p>
      )}
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="min-w-0 max-w-3xl">
          <h1 className="font-display text-[1.375rem] leading-7 font-semibold tracking-tight text-balance sm:text-title">{title}</h1>
          {meta && <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">{meta}</div>}
          {description && <p className="mt-1.5 text-sm text-muted-foreground text-pretty">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

/** The width a page's content keeps: lists, record pages or forms. */
export function Page({ width = "list", className, children }: { width?: "list" | "record" | "form"; className?: string; children: ReactNode }) {
  const max = width === "record" ? "max-w-[1280px]" : width === "form" ? "max-w-[720px]" : "max-w-[1200px]";
  return <div className={cn("mx-auto w-full", max, className)}>{children}</div>;
}
