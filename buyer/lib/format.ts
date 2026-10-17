import type { Grade } from "./types";

const cad = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
  maximumFractionDigits: 0,
});
const cadCents = new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD" });

/** "$24" for whole dollars, "$24.50" otherwise. */
export function formatPrice(n: number): string {
  return Number.isInteger(n) ? cad.format(n) : cadCents.format(n);
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400_000],
  ["hour", 3_600_000],
  ["minute", 60_000],
];
const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function relativeTime(iso: string, now: Date = new Date()): string {
  const diff = new Date(iso).getTime() - now.getTime();
  if (Number.isNaN(diff)) return "";
  for (const [unit, ms] of UNITS) {
    if (Math.abs(diff) >= ms) return rtf.format(Math.trunc(diff / ms), unit);
  }
  return "just now";
}

const GRADE_LABELS: Record<Grade, string> = {
  like_new: "Like new",
  light_wear: "Light wear",
  moderate_wear: "Moderate wear",
  heavy_wear: "Heavy wear",
};
export const conditionLabel = (g: Grade): string => GRADE_LABELS[g];
