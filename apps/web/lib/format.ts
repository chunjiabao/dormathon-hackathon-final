import { DISPLAY_TZ } from "./config";

const myr = new Intl.NumberFormat("en-MY", { style: "currency", currency: "MYR", minimumFractionDigits: 2 });
const myrPrecise = new Intl.NumberFormat("en-MY", {
  style: "currency",
  currency: "MYR",
  minimumFractionDigits: 4,
  maximumFractionDigits: 6,
});

export function formatMYR(v: number | null | undefined, precise = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return (precise ? myrPrecise : myr).format(v);
}

export function formatPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function formatNum(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-MY", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function formatMetric(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  return v.toFixed(digits);
}

/** Dashboard calendar date in Kuala Lumpur, independent of the browser timezone. */
export function calendarDaysAgo(n: number, now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: DISPLAY_TZ, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(now);
  const part = (kind: string) => parts.find((p) => p.type === kind)!.value;
  const day = new Date(`${part("year")}-${part("month")}-${part("day")}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() - n);
  return day.toISOString().slice(0, 10);
}

/** "2026-10-09" (a calendar date) -> "9 Oct 2026" without timezone shifting. */
export function formatDay(day: string | null | undefined, withYear = true): string {
  if (!day) return "—";
  const [y, m, d] = day.slice(0, 10).split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.toLocaleDateString("en-MY", {
    day: "numeric",
    month: "short",
    ...(withYear ? { year: "numeric" } : {}),
    timeZone: "UTC",
  });
}

/** Timestamp -> local Kuala Lumpur time. */
export function formatDateTime(ts: string | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts).toLocaleString("en-MY", {
    timeZone: DISPLAY_TZ,
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export const APP_LABELS: Record<string, string> = {
  bakery_demo: "BakeryBot",
  tuition_demo: "Tuition assistant",
  retail_demo: "Retail assistant",
};

export const CATEGORY_LABELS: Record<string, string> = {
  static_faq: "Static FAQs",
  order_enquiry: "Order enquiries",
  complex_support: "Complex support",
  other: "Other requests",
};

export const appLabel = (a: string | null | undefined) => (a ? (APP_LABELS[a] ?? a) : "—");
export const categoryLabel = (c: string) => CATEGORY_LABELS[c] ?? titleCase(c);
