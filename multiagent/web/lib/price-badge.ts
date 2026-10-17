export const GREAT_MAX = 0.85;
export const FAIR_MAX = 1.1;
export const HIGH_MAX = 1.3;

export type BadgeKind = "unknown" | "great" | "fair" | "high" | "overpriced";

const LABELS: Record<BadgeKind, string> = {
  unknown: "No price check",
  great: "Great price",
  fair: "Fair price",
  high: "A bit high",
  overpriced: "Overpriced",
};

export function priceBadge(
  price: number,
  ref: number | null,
): { kind: BadgeKind; label: string; pctVsFair: number | null } {
  if (ref === null || !(ref > 0)) return { kind: "unknown", label: LABELS.unknown, pctVsFair: null };
  const r = price / ref;
  const kind: BadgeKind =
    r <= GREAT_MAX ? "great" : r <= FAIR_MAX ? "fair" : r <= HIGH_MAX ? "high" : "overpriced";
  return { kind, label: LABELS[kind], pctVsFair: Math.round((r - 1) * 100) };
}

/** Sort key for "best deal": ascending ratio, unknowns last. */
export function dealRatio(price: number, ref: number | null): number {
  return ref !== null && ref > 0 ? price / ref : Number.POSITIVE_INFINITY;
}
