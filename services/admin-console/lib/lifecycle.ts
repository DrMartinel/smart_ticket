// Shapes the lifecycle endpoints return, and the canvas's connection-point geometry.

export interface Stage {
  id: string;
  name: string;
  description: string;
  color: string;
  order: number;
  is_backlog: boolean;
  is_completed: boolean;
}

export interface Action {
  id?: string;
  action: string;
  params: Record<string, string>;
  position: "before" | "after" | "both";
  is_active: boolean;
}

export interface Rule {
  id?: string;
  field_id: string;
  rule: string;
  params: Record<string, string>;
  is_active: boolean;
}

export interface Status {
  id: string;
  workflow_id: string;
  key: string;
  name: string;
  color: string;
  order: number;
  coordinates: string | null;
  base: Stage;
  is_pipeline: boolean;
  actions: Action[];
}

export type Point = "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8";

export interface Transition {
  id: string;
  workflow_id: string;
  from_status_id: string;
  to_status_id: string;
  name: string;
  point_start: Point;
  point_end: Point;
  is_bidirectional: boolean;
  rules: Rule[];
  actions: Action[];
}

export interface FieldEvent {
  id?: string;
  event: string;
  params: Record<string, string>;
  is_active: boolean;
  actions: Action[];
}

export interface Field {
  id: string;
  workflow_id: string;
  name: string;
  field_type: string;
  options: string[];
  order: number;
  rules: Omit<Rule, "field_id">[];
  events: FieldEvent[];
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  transition_policy: "strict" | "open";
  is_default: boolean;
  updated_at: string;
}

export interface WorkflowDetail extends Workflow {
  statuses: Status[];
  transitions: Transition[];
  fields: Field[];
}

export interface ActionParam {
  name: string;
  description: string;
  type: string;
  required: boolean;
}

export interface Catalog {
  field_types: string[];
  rules: { code: string; name: string; description: string; err_message: string; params: string[]; field_types: string[] }[];
  events: { code: string; name: string; description: string; params: string[] }[];
  actions: { code: string; name: string; description: string; blocking: boolean; phases: string[]; params: ActionParam[] }[];
  variables: Record<string, string>;
}

export const POINTS: Point[] = ["1", "2", "3", "4", "5", "6", "7", "8"];

// Clockwise from top-left: which side each point sits on, and how far along it.
export const POINT_PLACEMENT: Record<Point, { side: "top" | "right" | "bottom" | "left"; at: number }> = {
  "1": { side: "top", at: 25 },
  "2": { side: "top", at: 75 },
  "3": { side: "right", at: 25 },
  "4": { side: "right", at: 75 },
  "5": { side: "bottom", at: 75 },
  "6": { side: "bottom", at: 25 },
  "7": { side: "left", at: 75 },
  "8": { side: "left", at: 25 },
};

export function parseCoordinates(coordinates: string | null): { x: number; y: number } | null {
  if (!coordinates) return null;
  const [x, y] = coordinates.split("|").map(Number);
  return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
}

export const PALETTE = ["#6b665c", "#2d4f78", "#1f5c4a", "#2f6b45", "#85520b", "#a3271c", "#6a3d8a", "#0f6f7a"];
