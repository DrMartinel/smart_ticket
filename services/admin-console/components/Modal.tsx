"use client";

// A centred dialog over a dimmed page; Escape or the backdrop closes it.

import { useEffect, useRef, type ReactNode } from "react";

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
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      className={`m-auto w-[calc(100%-2rem)] ${width} rounded-[8px] border border-[var(--border)] bg-[var(--surface)] p-0 text-[var(--text)] shadow-xl backdrop:bg-black/30`}
    >
      {open && (
        <div className="flex max-h-[85dvh] flex-col">
          <header className="flex items-start justify-between gap-4 border-b border-[var(--border)] px-5 py-4">
            <div>
              <h2 className="text-base font-semibold">{title}</h2>
              {subtitle && <p className="mt-0.5 text-sm text-[var(--text-muted)]">{subtitle}</p>}
            </div>
            <button onClick={onClose} aria-label="Close" className="text-lg leading-none text-[var(--text-muted)] hover:text-[var(--text)]">
              ×
            </button>
          </header>
          <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && <footer className="flex justify-end gap-2 border-t border-[var(--border)] px-5 py-3">{footer}</footer>}
        </div>
      )}
    </dialog>
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
    <div role="tablist" className="mb-4 flex gap-5 border-b border-[var(--border)] text-sm">
      {tabs.map((t) => (
        <button
          key={t.key}
          role="tab"
          aria-selected={value === t.key}
          onClick={() => onChange(t.key)}
          className={`-mb-px border-b-2 pb-2 ${
            value === t.key ? "border-[var(--text)] font-medium" : "border-transparent text-[var(--text-muted)] hover:text-[var(--text)]"
          }`}
        >
          {t.label}
          {t.count ? <span className="ml-1.5 text-xs text-[var(--text-muted)]">{t.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function Labeled({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs font-medium text-[var(--text-muted)]">{label}</span>
      {children}
      {hint && <span className="text-xs text-[var(--text-muted)]">{hint}</span>}
    </label>
  );
}
