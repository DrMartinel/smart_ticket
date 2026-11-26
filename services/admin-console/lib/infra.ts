// The cloud's resources in the console (F17): their pages, the words for a query's receipt, and
// what each refusal of a change tells the person.

import { ApiError } from "./api";
import type {
  AgentActionOut,
  InfraBackend,
  InfraOutcome,
  InfraQueryKind,
  QueryCheck,
  RuleOut,
} from "./types/generated";

export type ResourceKind = "server" | "volume" | "network" | "security_group";

const SEGMENT: Record<ResourceKind, string> = {
  server: "servers",
  volume: "volumes",
  network: "networks",
  security_group: "security-groups",
};

export const RESOURCE_LABEL: Record<ResourceKind, string> = {
  server: "server",
  volume: "volume",
  network: "network",
  security_group: "security group",
};

/** The console page of a resource. */
export function resourceHref(kind: ResourceKind, id: string): string {
  return `/infra/${SEGMENT[kind]}/${encodeURIComponent(id)}`;
}

/** The resource an infra route's path is about, and its console page. */
export function resourceOfPath(path: string): { kind: ResourceKind; id: string; href: string } | null {
  const found = /\/api\/infra\/(servers|volumes|networks|security-groups)\/([^/]+)/.exec(path);
  if (!found) return null;
  const kind = (Object.keys(SEGMENT) as ResourceKind[]).find((k) => SEGMENT[k] === found[1])!;
  let id = found[2];
  try {
    id = decodeURIComponent(id);
  } catch {
    // keep the segment as written
  }
  return { kind, id, href: resourceHref(kind, id) };
}

export const BACKEND_LABEL: Record<InfraBackend, string> = {
  prometheus: "Prometheus",
  elasticsearch: "Elasticsearch",
  alertmanager: "Alertmanager",
  cloud: "Cloud API",
};

export const QUERY_KIND_LABEL: Record<InfraQueryKind, string> = {
  structured: "query",
  promql: "PromQL",
  resource: "resource read",
};

export const QUERY_OUTCOME: Record<InfraOutcome, { label: string; tone: "ok" | "warn" | "danger" }> = {
  ok: { label: "Ran", tone: "ok" },
  refused: { label: "Refused", tone: "warn" },
  backend_unavailable: { label: "Source down", tone: "danger" },
  scope_unavailable: { label: "Projects unread", tone: "danger" },
};

/** Why a query was refused, in a sentence. */
export const CHECK_TEXT: Record<QueryCheck, string> = {
  range: "Its time range is longer than allowed, or ends before it starts.",
  step: "Its step is finer than allowed.",
  series: "It matched more series than allowed; filter or aggregate it.",
  size: "It asked for more results than allowed.",
  field: "It names a label or field that isn't allowed.",
  dataset: "It names a metric or dataset that isn't allowed.",
  function: "It uses a function or aggregation that isn't allowed here.",
  match_all: "A matcher matches everything; name what it should match.",
  selectors: "It has more selectors than allowed.",
  unsupported: "It is written in a form that can't be checked; simplify it.",
  backend_refused: "The source refused it.",
};

/** What a refused query, or one whose source didn't answer, tells the person; null when it ran. */
export function queryRefusal(err: unknown): string | null {
  if (!(err instanceof ApiError)) return "Couldn't reach the server. Try again.";
  const details = (err.details ?? {}) as { reason?: QueryCheck; backend?: InfraBackend };
  switch (err.code) {
    case "infra_query_refused":
      return `Refused: ${details.reason ? CHECK_TEXT[details.reason] : err.message}`;
    case "infra_backend_unavailable":
      return `${details.backend ? BACKEND_LABEL[details.backend] : "The source"} didn't answer, so there are no results. That is not the same as nothing being wrong.`;
    case "infra_not_found":
      return "No such resource.";
    case "permission_missing":
      return "You can't read the cloud.";
  }
  return err.message;
}

// What a change's refusal tells the person. `final`: the action is no longer pending.
const CHANGE_REFUSAL: Record<string, { text: string; final?: boolean }> = {
  infra_state_changed: {
    text: "The resource changed since this was proposed, so nothing was sent. Read its state again; the draft stays.",
  },
  infra_ticket_required: {
    text: "A change has to name an open ticket you work on. Name one and apply again.",
  },
  infra_not_found: { text: "This resource no longer exists, or you can't reach it." },
  infra_backend_unavailable: { text: "The cloud didn't answer, so nothing was sent. You can try again." },
  infra_change_refused: { text: "The cloud refused this change. Nothing was changed." },
  permission_missing: { text: "You can't change the cloud's resources." },
  agent_action_expired: { text: "This has expired. Ask the assistant again if you still want it.", final: true },
  agent_action_not_pending: { text: "This can no longer be applied. Ask the assistant again if you still want it.", final: true },
  agent_action_mismatch: { text: "This isn't the change the assistant proposed, so it wasn't sent." },
};

/** What a lost answer to a change tells the person (BR-F17-09): check the resource, never resend. */
export const OUTCOME_UNKNOWN_TEXT =
  "The cloud's answer was lost, so it isn't known whether the change was made. Check the resource before doing anything else.";

export type ChangeResult =
  | { kind: "unknown"; text: string }
  | { kind: "final"; text: string }
  | { kind: "refused"; text: string };

/** What became of a change the cloud did not accept, from its refusal's code. */
export function changeRefusal(err: unknown): ChangeResult {
  if (!(err instanceof ApiError)) return { kind: "refused", text: "Couldn't reach the server." };
  if (err.code === "infra_outcome_unknown") return { kind: "unknown", text: OUTCOME_UNKNOWN_TEXT };
  const known = err.code ? CHANGE_REFUSAL[err.code] : undefined;
  if (known) return { kind: known.final ? "final" : "refused", text: known.text };
  return { kind: "refused", text: err.message };
}

export type ChangeKind =
  | "soft_reboot"
  | "hard_reboot"
  | "start"
  | "stop"
  | "attach_volume"
  | "detach_volume"
  | "add_security_rule"
  | "remove_security_rule";

export const CHANGE_LABEL: Record<ChangeKind, string> = {
  soft_reboot: "Soft reboot",
  hard_reboot: "Hard reboot",
  start: "Start",
  stop: "Stop",
  attach_volume: "Attach the volume",
  detach_volume: "Detach the volume",
  add_security_rule: "Add a security rule",
  remove_security_rule: "Remove a security rule",
};

/** The change an assistant's action on an infra route makes, read from its method and path. */
export function changeOf(action: Pick<AgentActionOut, "method" | "path">): ChangeKind | null {
  const tail = /\/api\/infra\/[^/]+\/[^/]+\/([a-z-]+)\/?$/.exec(action.path)?.[1];
  switch (tail) {
    case "reboot":
      return "soft_reboot";
    case "hard-reboot":
      return "hard_reboot";
    case "start":
      return "start";
    case "stop":
      return "stop";
    case "attach":
      return "attach_volume";
    case "detach":
      return "detach_volume";
    case "rules":
      return action.method === "DELETE" ? "remove_security_rule" : "add_security_rule";
  }
  return null;
}

/** A security group rule in a few words, e.g. `ingress tcp 5432 from 10.10.0.0/24`. */
export function describeRule(rule: Pick<RuleOut, "direction" | "protocol" | "port_min" | "port_max" | "remote_ip_prefix">): string {
  const ports =
    rule.port_min === null ? "" : rule.port_max === null || rule.port_max === rule.port_min ? ` ${rule.port_min}` : ` ${rule.port_min}-${rule.port_max}`;
  const side = rule.direction === "ingress" ? "from" : "to";
  return `${rule.direction} ${rule.protocol ?? "any"}${ports} ${side} ${rule.remote_ip_prefix ?? "anywhere"}`;
}

/** The last `hours` as the routes take a window, in about 120 steps of at least a minute. */
export function windowOf(hours: number): { start: string; end: string; step_seconds: number } {
  const end = new Date();
  const start = new Date(end.getTime() - hours * 3_600_000);
  const step_seconds = Math.max(60, Math.round((hours * 3600) / 120 / 60) * 60);
  return { start: start.toISOString(), end: end.toISOString(), step_seconds };
}
