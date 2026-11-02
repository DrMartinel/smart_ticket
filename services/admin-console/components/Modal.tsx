"use client";

// A centred dialog over a dimmed page; Escape or the backdrop closes it.

import { type ReactNode } from "react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs as TabsRoot, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

export default function Modal({
  open,
  title,
  subtitle,
  onClose,
  children,
  footer,
  width = "max-w-xl",
}: {
  open: boolean;
  title: string;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: string;
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className={cn("flex max-h-[85dvh] flex-col gap-0 p-0 sm:max-w-xl", width.replace(/(^|\s)max-w-/g, "$1sm:max-w-"))}>
        <DialogHeader className="border-b px-5 py-4 pr-12">
          <DialogTitle className="text-base">{title}</DialogTitle>
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

export function Labeled({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}
