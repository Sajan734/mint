import type { Grade } from "./types";

export const formatPrice = (cad: number) =>
  new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 }).format(cad);

export const GRADE_LABEL: Record<Grade, string> = {
  like_new: "Like new",
  light_wear: "Light wear",
  moderate_wear: "Moderate wear",
  heavy_wear: "Heavy wear",
};
