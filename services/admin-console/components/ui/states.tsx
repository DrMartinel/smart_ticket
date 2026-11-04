// The one loading, empty and error pattern every data view uses.

import type { ReactNode } from "react";
import { AlertTriangle, Inbox, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("skeleton h-4", className)} />;
}

/** Placeholder rows shown while a list or page loads. */
export function LoadingState({ rows = 4, label = "Loading", className }: { rows?: number; label?: string; className?: string }) {
  return (
    <div role="status" aria-live="polite" className={cn("flex flex-col gap-3 py-2", className)}>
      <span className="sr-only">{label}…</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4">
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="hidden h-4 w-24 sm:block" />
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

/** Nothing to show yet: what this is, and what to do next. */
export function EmptyState({
  icon: Icon = Inbox,
  title,
  children,
  action,
  compact = false,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center text-center", compact ? "gap-2 px-4 py-6" : "gap-3 px-6 py-12", className)}>
      <span
        aria-hidden
        className={cn(
          "flex items-center justify-center rounded-md border border-dashed border-border-strong text-muted-foreground",
          compact ? "size-9" : "size-12",
        )}
      >
        <Icon className={compact ? "size-4" : "size-5"} strokeWidth={1.5} />
      </span>
      <div className="max-w-sm">
        <p className="text-sm font-medium text-foreground">{title}</p>
        {children && <div className="mt-1 text-sm text-muted-foreground text-pretty">{children}</div>}
      </div>
      {action && <div className="mt-1 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}

/** Something failed to load: what, and a way to try again. */
export function ErrorState({
  title = "This didn't load",
  children,
  onRetry,
  compact = false,
  className,
}: {
  title?: string;
  children?: ReactNode;
  onRetry?: () => void;
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 rounded-md border border-danger/25 bg-danger-soft text-danger",
        compact ? "px-3 py-2.5" : "px-4 py-3.5",
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-medium">{title}</p>
        {children && <div className="mt-0.5 text-danger/90">{children}</div>}
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry} className="shrink-0 border-danger/30 bg-transparent text-danger hover:bg-danger/10 hover:text-danger">
          Try again
        </Button>
      )}
    </div>
  );
}

/** A table body's status row: placeholders while loading, the empty state when there are no rows. */
export function TableStatus({
  colSpan,
  rows,
  error = false,
  empty,
}: {
  colSpan: number;
  rows: readonly unknown[] | null | undefined;
  error?: boolean;
  empty: ReactNode;
}) {
  if (error || (rows && rows.length > 0)) return null;
  return (
    <tr className="hover:bg-transparent">
      <td colSpan={colSpan} className="px-4 py-2">
        {rows ? empty : <LoadingState rows={3} />}
      </td>
    </tr>
  );
}
