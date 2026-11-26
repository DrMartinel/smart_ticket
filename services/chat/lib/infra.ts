// The customer's cloud tools in the chat (F17): what each is called, which ones only read, what a
// server change does and says once made, and what each refusal of it tells the person.

import type { InfraChange } from "./types/generated";

/** What each cloud tool of the chat is called in a receipt or a confirmation card. */
export const CLOUD_TOOL_LABEL: Record<string, string> = {
  my_infra_catalog: "What can be looked up",
  list_my_projects: "Your projects",
  list_my_servers: "Your servers",
  get_my_server: "One of your servers",
  list_my_volumes: "Your volumes",
  get_my_volume: "One of your volumes",
  list_my_networks: "Your networks",
  get_my_network: "One of your networks",
  list_my_alerts: "Your alerts",
  list_my_silences: "Your alert silences",
  query_my_metrics: "Your metrics",
  search_my_logs: "Your logs",
  search_my_traces: "Your traces",
  get_my_trace: "One of your traces",
  reboot_my_server: "Restart your server",
  start_my_server: "Start your server",
  stop_my_server: "Stop your server",
};

/** The cloud tools that only read. */
export const CLOUD_READS: ReadonlySet<string> = new Set([
  "my_infra_catalog",
  "list_my_projects",
  "list_my_servers",
  "get_my_server",
  "list_my_volumes",
  "get_my_volume",
  "list_my_networks",
  "get_my_network",
  "list_my_alerts",
  "list_my_silences",
  "query_my_metrics",
  "search_my_logs",
  "search_my_traces",
  "get_my_trace",
]);

/** What each server change the person confirms does. */
export const SERVER_CHANGE: Record<string, string> = {
  reboot_my_server: "Restarts the server's operating system (a soft reboot).",
  start_my_server: "Starts the server.",
  stop_my_server: "Shuts the server down. It stays off until it is started again.",
};

/** What a change the cloud accepted says; null for a change a customer can't make. */
export function changeDone(change: InfraChange, name: string): string | null {
  switch (change) {
    case "soft_reboot":
      return `${name} is restarting.`;
    case "start":
      return `${name} is starting.`;
    case "stop":
      return `${name} is stopping.`;
    default:
      return null;
  }
}

const SERVER_STATE: Record<string, string> = {
  ACTIVE: "running",
  SHUTOFF: "stopped",
  REBOOT: "restarting",
  HARD_REBOOT: "restarting",
  ERROR: "in an error state",
};

/** A server's status, in words. */
export function serverState(status: string): string {
  return SERVER_STATE[status] ?? status.toLowerCase();
}

/** What a refused server change tells the person; the change still waits for them. */
export const CHANGE_REFUSAL: Record<string, string> = {
  infra_state_changed: "The server isn't in a state that allows this right now, so nothing was sent.",
  infra_not_found: "This server isn't among yours any more, so nothing was sent.",
  infra_scope_unavailable: "I couldn't check which projects are yours just now, so nothing was sent. Try again in a moment.",
  infra_backend_unavailable: "The cloud didn't answer, so nothing was sent. Try again in a moment.",
  infra_change_refused: "The cloud refused this change, so nothing changed.",
};

/** What a change whose answer was lost tells the person (F17 BR-F17-09); it is never sent again. */
export const OUTCOME_UNKNOWN_TEXT =
  "I couldn't tell whether that went through. Check the server before asking again; it won't be sent twice.";
