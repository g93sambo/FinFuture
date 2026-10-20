const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usdWhole = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const num = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export const money = (v: number | null | undefined) => (isNum(v) ? usd.format(v) : "–");
export const moneyWhole = (v: number | null | undefined) => (isNum(v) ? usdWhole.format(v) : "–");
export const qty = (v: number | null | undefined) => (isNum(v) ? num.format(v) : "–");
export const big = (v: number | null | undefined) => (isNum(v) ? compact.format(v) : "–");

/** 0.1234 -> "12.3%" */
export const pct = (v: number | null | undefined, digits = 1) => (isNum(v) ? `${(v * 100).toFixed(digits)}%` : "–");
/** Signed fraction: 0.012 -> "+1.2%" */
export const signedPct = (v: number | null | undefined, digits = 1) =>
  isNum(v) ? `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(digits)}%` : "–";
/** A value already expressed in percent points: 4.5 -> "4.50%" */
export const points = (v: number | null | undefined, digits = 2) => (isNum(v) ? `${v.toFixed(digits)}%` : "–");
export const fixed = (v: number | null | undefined, digits = 2) => (isNum(v) ? v.toFixed(digits) : "–");

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function timeOnly(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

/** snake_case / SCREAMING_CASE -> "Sentence case" */
export function humanize(s: string | null | undefined): string {
  if (!s) return "–";
  const t = s.replace(/[_-]+/g, " ").trim().toLowerCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export const shortHash = (h: string | null | undefined, n = 10) => (h ? `${h.slice(0, n)}…${h.slice(-4)}` : "–");

/**
 * Broker order statuses in words a client understands. Market orders placed while the
 * exchange is closed stay "new"/"accepted" at the broker until the next session opens.
 */
export function orderStatus(status: string | null | undefined): { label: string; tone: "success" | "warning" | "danger" | "neutral"; filled: boolean } {
  const s = (status ?? "").toUpperCase();
  if (s === "FILLED") return { label: "Filled", tone: "success", filled: true };
  if (s === "PARTIALLY_FILLED") return { label: "Partly filled", tone: "warning", filled: false };
  if (["CANCELED", "CANCELLED", "PENDING_CANCEL"].includes(s)) return { label: "Cancelled", tone: "neutral", filled: false };
  if (["EXPIRED", "DONE_FOR_DAY"].includes(s)) return { label: "Expired", tone: "neutral", filled: false };
  if (["REJECTED", "BLOCKED", "SUSPENDED"].includes(s)) return { label: "Rejected", tone: "danger", filled: false };
  return { label: "Queued", tone: "neutral", filled: false };
}

/** Short, readable reference for an order or account (the full broker ID stays available as a tooltip). */
export const shortRef = (id: string | null | undefined) => (id ? id.replace(/-/g, "").slice(-8).toUpperCase() : "–");
