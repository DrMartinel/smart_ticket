"use client";

import { Switch as SwitchRoot } from "@/components/ui/switch";

/** An on/off switch; a locked one shows its state and can't be changed. */
export default function Switch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onChange?: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return <SwitchRoot checked={checked} onCheckedChange={(next) => onChange?.(next)} aria-label={label} disabled={disabled} />;
}
