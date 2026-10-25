// Display helpers shared by every page.

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** "3 min ago", "in 2 h", "4 Oct". */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  const future = seconds > 0;
  if (abs < MINUTE) return future ? "in a moment" : "just now";
  if (abs < HOUR) return phrase(Math.round(abs / MINUTE), "min", future);
  if (abs < DAY) return phrase(Math.round(abs / HOUR), "h", future);
  if (abs < 7 * DAY) return phrase(Math.round(abs / DAY), "d", future);
  return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short" });
}

function phrase(n: number, unit: string, future: boolean): string {
  return future ? `in ${n} ${unit}` : `${n} ${unit} ago`;
}

/** A full timestamp for tooltips and detail pages. */
export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** "42 s", "38 min", "1 h 16 min", "2 d 4 h". */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.round(seconds);
  if (s < MINUTE) return `${s} s`;
  if (s < HOUR) return `${Math.round(s / MINUTE)} min`;
  if (s < DAY) {
    const h = Math.floor(s / HOUR);
    const m = Math.round((s % HOUR) / MINUTE);
    return m ? `${h} h ${m} min` : `${h} h`;
  }
  const d = Math.floor(s / DAY);
  const h = Math.round((s % DAY) / HOUR);
  return h ? `${d} d ${h} h` : `${d} d`;
}

export function percent(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)}%`;
}

export function humanize(code: string | null | undefined): string {
  if (!code) return "—";
  const text = code.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
