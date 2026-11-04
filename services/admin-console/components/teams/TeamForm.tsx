"use client";

// A team's settings form (F2): name, strategy, cap, owned categories, fallback and the reason for a save.

import type { TeamOut, TeamStrategy, TicketCategory } from "@/lib/types/generated";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";

export const CATEGORIES: TicketCategory[] = ["hardware", "software", "network", "access", "security", "other"];

export const STRATEGY_LABEL: Record<string, string> = {
  least_loaded: "Fewest open tickets",
  round_robin: "Assigned longest ago",
};

export interface TeamDraft {
  slug: string;
  name: string;
  categories: TicketCategory[];
  strategy: TeamStrategy;
  max_open_per_member: string;
  is_fallback: boolean;
  is_active: boolean;
  reason: string;
}

export const BLANK_TEAM: TeamDraft = {
  slug: "",
  name: "",
  categories: [],
  strategy: "least_loaded",
  max_open_per_member: "",
  is_fallback: false,
  is_active: true,
  reason: "",
};

export function draftOf(team: TeamOut): TeamDraft {
  return {
    slug: team.slug,
    name: team.name,
    categories: team.categories as TicketCategory[],
    strategy: team.strategy as TeamStrategy,
    max_open_per_member: team.max_open_per_member ? String(team.max_open_per_member) : "",
    is_fallback: team.is_fallback,
    is_active: team.is_active,
    reason: "",
  };
}

/** The request body a save sends: the slug only when creating, the active flag only when editing. */
export function bodyOf(d: TeamDraft, create: boolean, move = false) {
  return {
    name: d.name,
    categories: d.categories,
    strategy: d.strategy,
    max_open_per_member: d.max_open_per_member ? Number(d.max_open_per_member) : null,
    is_fallback: d.is_fallback,
    move_categories: move,
    reason: d.reason,
    ...(create ? { slug: d.slug } : { is_active: d.is_active }),
  };
}

export function TeamForm({
  draft: d,
  create,
  disabled = false,
  onChange,
}: {
  draft: TeamDraft;
  create: boolean;
  disabled?: boolean;
  onChange: (patch: Partial<TeamDraft>) => void;
}) {
  return (
    <div className="flex flex-col gap-4 text-sm">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Name</span>
          <Input value={d.name} disabled={disabled} onChange={(e) => onChange({ name: e.target.value })} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Slug (used in links and reports)</span>
          <Input
            className="font-mono"
            value={d.slug}
            disabled={!create || disabled}
            placeholder="cloud-platform"
            onChange={(e) => onChange({ slug: e.target.value.toLowerCase() })}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Who gets the next ticket</span>
          <NativeSelect
            value={d.strategy}
            disabled={disabled}
            onChange={(e) => onChange({ strategy: e.target.value as TeamStrategy })}
          >
            {Object.entries(STRATEGY_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </NativeSelect>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Open tickets per member (cap)</span>
          <Input
            type="number"
            min={1}
            value={d.max_open_per_member}
            disabled={disabled}
            placeholder="No cap"
            onChange={(e) => onChange({ max_open_per_member: e.target.value })}
          />
        </label>
      </div>
      <fieldset className="flex flex-wrap gap-x-4 gap-y-1.5" disabled={disabled}>
        <legend className="pb-1.5 text-xs text-muted-foreground">Categories it owns</legend>
        {CATEGORIES.map((c) => (
          <label key={c} className="flex items-center gap-1.5">
            <Checkbox
              checked={d.categories.includes(c)}
              disabled={disabled}
              onCheckedChange={() =>
                onChange({ categories: d.categories.includes(c) ? d.categories.filter((x) => x !== c) : [...d.categories, c] })
              }
            />
            {c}
          </label>
        ))}
      </fieldset>
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <label className="flex items-center gap-1.5">
          <Checkbox checked={d.is_fallback} disabled={disabled} onCheckedChange={(on) => onChange({ is_fallback: on === true })} />
          Fallback team (gets tickets whose category no team owns)
        </label>
        {!create && (
          <label className="flex items-center gap-1.5">
            <Checkbox checked={d.is_active} disabled={disabled} onCheckedChange={(on) => onChange({ is_active: on === true })} />
            Active
          </label>
        )}
      </div>
      {!disabled && (
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Reason for this change (kept in the audit log)</span>
          <Input value={d.reason} maxLength={500} onChange={(e) => onChange({ reason: e.target.value })} />
        </label>
      )}
    </div>
  );
}
