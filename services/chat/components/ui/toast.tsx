"use client";

// Short confirmations of an action, shown at the bottom of the screen and read out to screen readers.

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { CheckCircle2, AlertTriangle, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

type Tone = "ok" | "danger" | "info";

interface Toast {
  id: number;
  tone: Tone;
  message: ReactNode;
  action?: { label: string; onClick: () => void };
}

interface ToastApi {
  success: (message: ReactNode, action?: Toast["action"]) => void;
  error: (message: ReactNode) => void;
  info: (message: ReactNode) => void;
}

const ToastContext = createContext<ToastApi>({ success: () => undefined, error: () => undefined, info: () => undefined });

const LIFETIME_MS: Record<Tone, number> = { ok: 4000, info: 5000, danger: 7000 };

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

export function Toaster({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);

  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), []);

  const push = useCallback(
    (tone: Tone, message: ReactNode, action?: Toast["action"]) => {
      const id = next.current++;
      setToasts((all) => [...all.slice(-2), { id, tone, message, action }]);
      setTimeout(() => dismiss(id), LIFETIME_MS[tone]);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (m, a) => push("ok", m, a),
      error: (m) => push("danger", m),
      info: (m) => push("info", m),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 sm:items-end sm:p-6"
      >
        {toasts.map((t) => {
          const Icon = t.tone === "ok" ? CheckCircle2 : t.tone === "danger" ? AlertTriangle : Info;
          return (
            <div
              key={t.id}
              role={t.tone === "danger" ? "alert" : "status"}
              className={cn(
                "pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-md border bg-popover px-4 py-3 text-sm text-popover-foreground shadow-float",
                "animate-in fade-in slide-in-from-bottom-2 duration-200",
                t.tone === "danger" ? "border-danger/30" : "border-border",
              )}
            >
              <Icon className={cn("mt-0.5 size-4 shrink-0", t.tone === "ok" ? "text-ok" : t.tone === "danger" ? "text-danger" : "text-info")} aria-hidden />
              <div className="min-w-0 flex-1">{t.message}</div>
              {t.action && (
                <button
                  className="shrink-0 font-medium text-primary hover:underline"
                  onClick={() => {
                    t.action!.onClick();
                    dismiss(t.id);
                  }}
                >
                  {t.action.label}
                </button>
              )}
              <button aria-label="Dismiss" className="-mr-1 shrink-0 rounded text-muted-foreground hover:text-foreground" onClick={() => dismiss(t.id)}>
                <X className="size-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
