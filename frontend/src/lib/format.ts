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
