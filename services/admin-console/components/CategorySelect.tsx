"use client";

// A category select: the active categories by name, the current value when it is not among them, and
// why the list is missing when it couldn't be read (ADR-0049).

import type { ComponentProps } from "react";
import { NativeSelect } from "@/components/ui/native-select";
import { useCategories } from "@/lib/categories";

/** The reason the categories couldn't be read, with a retry. */
export function CategoryReadError({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <span role="alert" className="text-xs text-danger">
      {error}{" "}
      <button type="button" className="underline underline-offset-2" onClick={onRetry}>
        Try again
      </button>
    </span>
  );
}

export function CategorySelect({
  value,
  blank,
  ...props
}: Omit<ComponentProps<typeof NativeSelect>, "children" | "value"> & {
  value: string | null | undefined;
  blank?: string;
}) {
  const { categories, error, retry } = useCategories();
  return (
    <>
      <NativeSelect {...props} value={value ?? ""} aria-invalid={error ? true : props["aria-invalid"]}>
        {blank !== undefined && <option value="">{blank}</option>}
        {value && !categories.some((c) => c.slug === value) && <option value={value}>{value}</option>}
        {categories.map((c) => (
          <option key={c.slug} value={c.slug}>
            {c.name}
          </option>
        ))}
      </NativeSelect>
      {error && <CategoryReadError error={error} onRetry={retry} />}
    </>
  );
}
