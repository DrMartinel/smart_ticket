"use client";

// A centred dialog over a dimmed page; Escape or the backdrop closes it.

import { type ReactNode } from "react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs as TabsRoot, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

// Literal classes, so Tailwind's source scan generates each one.
const WIDTHS = {
  sm: "sm:max-w-md",
  md: "sm:max-w-[520px]",
  lg: "sm:max-w-xl",
  xl: "sm:max-w-2xl",
  "2xl": "sm:max-w-3xl",
} as const;

export type ModalSize = keyof typeof WIDTHS;

export default function Modal({
  open,
  title,
  subtitle,
  onClose,
  children,
  footer,
  size = "lg",
}: {
  open: boolean;
  title: string;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  size?: ModalSize;
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className={cn("flex max-h-[85dvh] flex-col gap-0 p-0", WIDTHS[size])}>
        <DialogHeader className="border-b px-5 py-4 pr-14 text-left">
          <DialogTitle className="font-display text-lg leading-6 font-semibold">{title}</DialogTitle>
          {subtitle ? <DialogDescription>{subtitle}</DialogDescription> : <DialogDescription className="sr-only">{title}</DialogDescription>}
        </DialogHeader>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <DialogFooter className="border-t px-5 py-3">{footer}</DialogFooter>}
      </DialogContent>
    </Dialog>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { key: T; label: string; count?: number }[];
  value: T;
  onChange: (key: T) => void;
}) {
  return (
    <TabsRoot value={value} onValueChange={(next) => onChange(next as T)} className="mb-4">
      <TabsList>
        {tabs.map((t) => (
          <TabsTrigger key={t.key} value={t.key}>
            {t.label}
            {t.count ? <span className="text-xs text-muted-foreground">{t.count}</span> : null}
          </TabsTrigger>
        ))}
      </TabsList>
    </TabsRoot>
  );
}

/** A form field: its label (marked when required), the control, a hint and an inline error. */
export function Labeled({
  label,
  hint,
  error,
  required = false,
  className,
  children,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  required?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <label className={cn("flex min-w-0 flex-col gap-1.5 text-sm", className)}>
      <span className="text-xs font-medium text-foreground/80">
        {label}
        {required && (
          <span className="ml-0.5 text-danger" aria-hidden>
            *
          </span>
        )}
        {required && <span className="sr-only"> (required)</span>}
      </span>
      {children}
      {error ? (
        <span role="alert" className="text-xs text-danger">
          {error}
        </span>
      ) : (
        hint && <span className="text-xs text-muted-foreground">{hint}</span>
      )}
    </label>
  );
}
