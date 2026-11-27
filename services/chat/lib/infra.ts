// The customer's cloud in the chat (F17): what each server change is called, does and says once
// made, what each refusal of it tells the person, and the words for a query's receipt.

import type { InfraBackend, InfraChange, InfraOutcome, Language, QueryCheck } from "./types/generated";

/** What each server change of the chat is called on its receipt and its confirmation card. */
export const CLOUD_TOOL_LABEL: Record<string, string> = {
  reboot_my_server: "Restart your server",
  start_my_server: "Start your server",
  stop_my_server: "Stop your server",
};

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

/** The words of a query's receipt in one language. */
type ReceiptWords = {
  heading: string;
  missing: string;
  outcome: Record<InfraOutcome, string>;
  looked: Record<InfraBackend, string>;
  source: Record<InfraBackend, string>;
  results: (n: number) => string;
  cut: string;
  noAnswer: (source: string) => string;
  check: Record<QueryCheck, string>;
  notFound: string;
  refused: string;
};

/** The words of a query's receipt, by the turn's language. */
export const RECEIPT_WORDS: Record<Language, ReceiptWords> = {
  en: {
    heading: "What the assistant looked at",
    missing: "Missing from this answer",
    outcome: {
      ok: "Looked up",
      refused: "Refused",
      backend_unavailable: "No answer",
      scope_unavailable: "Projects unread",
    },
    looked: {
      prometheus: "Metrics",
      elasticsearch: "Logs and traces",
      alertmanager: "Alerts",
      cloud: "Resources",
    },
    source: {
      prometheus: "Prometheus",
      elasticsearch: "Elasticsearch",
      alertmanager: "Alertmanager",
      cloud: "The cloud's API",
    },
    results: (n) => `${n} ${n === 1 ? "result" : "results"}`,
    cut: "cut at the size limit, so some results are missing",
    noAnswer: (source) => `${source} didn't answer`,
    check: {
      range: "Its time range was longer than allowed, or ended before it started.",
      step: "Its step was finer than allowed.",
      series: "It matched more series than allowed.",
      size: "It asked for more results than allowed.",
      field: "It named a label or field that isn't allowed.",
      dataset: "It named a metric or dataset that isn't allowed.",
      function: "It used a function that isn't allowed.",
      match_all: "It would have matched everything.",
      selectors: "It had more filters than allowed.",
      unsupported: "It was written in a form that can't be checked.",
      backend_refused: "The source refused it.",
    },
    notFound: "No such resource among yours.",
    refused: "Refused.",
  },
  vi: {
    heading: "Những gì trợ lý đã xem",
    missing: "Thiếu trong câu trả lời này",
    outcome: {
      ok: "Đã xem",
      refused: "Bị từ chối",
      backend_unavailable: "Không phản hồi",
      scope_unavailable: "Không đọc được dự án",
    },
    looked: {
      prometheus: "Số liệu đo",
      elasticsearch: "Log và trace",
      alertmanager: "Cảnh báo",
      cloud: "Tài nguyên",
    },
    source: {
      prometheus: "Prometheus",
      elasticsearch: "Elasticsearch",
      alertmanager: "Alertmanager",
      cloud: "API của hệ thống cloud",
    },
    results: (n) => `${n} kết quả`,
    cut: "bị cắt ở giới hạn kích thước nên thiếu một số kết quả",
    noAnswer: (source) => `${source} không phản hồi`,
    check: {
      range: "Khoảng thời gian dài hơn mức cho phép, hoặc kết thúc trước khi bắt đầu.",
      step: "Bước thời gian nhỏ hơn mức cho phép.",
      series: "Khớp nhiều chuỗi số liệu hơn mức cho phép.",
      size: "Yêu cầu nhiều kết quả hơn mức cho phép.",
      field: "Dùng một nhãn hoặc trường không được phép.",
      dataset: "Dùng một số liệu hoặc tập dữ liệu không được phép.",
      function: "Dùng một hàm không được phép.",
      match_all: "Điều kiện lọc khớp với mọi thứ.",
      selectors: "Có nhiều bộ lọc hơn mức cho phép.",
      unsupported: "Được viết ở dạng không kiểm tra được.",
      backend_refused: "Nguồn dữ liệu đã từ chối.",
    },
    notFound: "Không có tài nguyên này trong số tài nguyên của bạn.",
    refused: "Bị từ chối.",
  },
};

/** The badge tone of a query's outcome. */
export const QUERY_TONE: Record<InfraOutcome, "ok" | "warn" | "danger"> = {
  ok: "ok",
  refused: "warn",
  backend_unavailable: "danger",
  scope_unavailable: "danger",
};
