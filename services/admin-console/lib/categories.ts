"use client";

// The ticket categories every category picker offers, read from core-api (ADR-0049).

import { useEffect, useState } from "react";
import { ApiError, api } from "./api";
import type { CategoryOut } from "./types/generated";

let loading: Promise<CategoryOut[]> | null = null;

/** Every category, read once per page load. */
export function loadCategories(): Promise<CategoryOut[]> {
  if (!loading) {
    const request: Promise<CategoryOut[]> = api.get<CategoryOut[]>("/api/categories").catch((e: unknown) => {
      if (loading === request) loading = null;
      throw e;
    });
    loading = request;
  }
  return loading;
}

/** Drops the cached list, so the next read sees an edit. */
export function forgetCategories(): void {
  loading = null;
}

export interface Categories {
  categories: CategoryOut[];
  error: string | null;
  retry: () => void;
}

/** The active categories in display order, and why they couldn't be read when they couldn't. */
export function useCategories(): Categories {
  const [categories, setCategories] = useState<CategoryOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    loadCategories()
      .then((all) => {
        if (!alive) return;
        setCategories(all.filter((c) => c.is_active));
        setError(null);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(
          e instanceof ApiError && e.code === "permission_missing"
            ? "You don't have permission to read the categories."
            : "Couldn't load the categories.",
        );
      });
    return () => {
      alive = false;
    };
  }, [attempt]);
  return { categories, error, retry: () => setAttempt((n) => n + 1) };
}

/** Sets an empty `value` to the first active category once the categories load. */
export function useFirstCategoryWhenEmpty(value: string | null | undefined, setValue: (slug: string) => void): void {
  const { categories } = useCategories();
  useEffect(() => {
    if (!value && categories.length > 0) setValue(categories[0].slug);
  }, [value, categories, setValue]);
}
