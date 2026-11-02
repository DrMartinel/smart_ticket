"use client";

// Runs the step-by-step guides: which one is open, on which step, and which ones a user has finished.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { TOURS, FIRST_TOUR } from "@/lib/tours";
import TourOverlay from "./TourOverlay";
import type { Tour } from "./types";

interface Run {
  id: string;
  step: number;
}

interface TourState {
  /** The guides this user may take. */
  tours: Tour[];
  done: string[];
  start: (id: string) => void;
}

const TourContext = createContext<TourState>({ tours: [], done: [], start: () => undefined });

const RUN_KEY = "smart-ticket:tour-run";
const doneKey = (userId: string) => `smart-ticket:tours-done:${userId}`;

function read<T>(storage: () => Storage, key: string, fallback: T): T {
  try {
    const raw = storage().getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(storage: () => Storage, key: string, value: unknown) {
  try {
    if (value === null) storage().removeItem(key);
    else storage().setItem(key, JSON.stringify(value));
  } catch {
    // Storage is blocked: the guide runs unremembered.
  }
}


export function TourProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const router = useRouter();
  const pathname = usePathname() ?? "";
  const [run, setRun] = useState<Run | null>(null);
  const [done, setDone] = useState<string[]>([]);

  const tours = useMemo(
    () =>
      user
        ? TOURS.filter((t) => t.audience(user)).map((t) => ({ ...t, steps: t.steps.filter((s) => !s.when || s.when(user)) }))
        : [],
    [user],
  );
  const tour = run ? tours.find((t) => t.id === run.id) ?? null : null;
  const step = tour && run ? tour.steps[run.step] ?? null : null;

  const settledFor = useRef<string | null>(null);

  useEffect(() => {
    if (!user) {
      if (settledFor.current) write(() => sessionStorage, RUN_KEY, null);
      settledFor.current = null;
      setRun(null);
      return;
    }
    if (settledFor.current === user.id || /^\/(login|auth)/.test(pathname)) return;
    settledFor.current = user.id;
    const seen = read<string[]>(() => localStorage, doneKey(user.id), []);
    setDone(seen);
    const saved = read<Run | null>(() => sessionStorage, RUN_KEY, null);
    if (saved) setRun(saved);
    else if (!seen.includes(FIRST_TOUR)) setRun({ id: FIRST_TOUR, step: 0 });
    // Settles the guide state once per sign-in.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, pathname]);

  useEffect(() => {
    if (settledFor.current) write(() => sessionStorage, RUN_KEY, run);
  }, [run]);

  useEffect(() => {
    if (step?.href && step.href !== pathname) router.push(step.href);
    // Opens the step's page when the step starts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id, run?.step]);

  const finish = useCallback(() => {
    if (user && run) {
      const next = [...new Set([...done, run.id])];
      setDone(next);
      write(() => localStorage, doneKey(user.id), next);
    }
    setRun(null);
  }, [user, run, done]);

  const start = useCallback((id: string) => setRun({ id, step: 0 }), []);

  const value = useMemo(() => ({ tours, done, start }), [tours, done, start]);

  return (
    <TourContext.Provider value={value}>
      {children}
      {tour && step && run && user && (
        <TourOverlay
          key={`${run.id}:${run.step}`}
          step={step}
          index={run.step}
          count={tour.steps.length}
          language={user.language ?? "vi"}
          onBack={() => setRun({ ...run, step: Math.max(0, run.step - 1) })}
          onNext={() => (run.step + 1 >= tour.steps.length ? finish() : setRun({ ...run, step: run.step + 1 }))}
          onClose={finish}
          pathname={pathname}
        />
      )}
    </TourContext.Provider>
  );
}

export function useTours(): TourState {
  return useContext(TourContext);
}
