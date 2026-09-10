/**
 * NAVIGUIDE v2 — Risk colour utilities
 * Shared across map layers, badges, and sidebar components.
 */

/** Tailwind bg + text class pair for risk level badges */
export const riskBadgeClass = {
  LOW:      "bg-green-900/60  text-green-300  border border-green-700",
  MODERATE: "bg-yellow-900/60 text-yellow-300 border border-yellow-700",
  HIGH:     "bg-orange-900/60 text-orange-300 border border-orange-700",
  CRITICAL: "bg-red-900/60    text-red-300    border border-red-700",
  UNKNOWN:  "bg-slate-800     text-slate-400  border border-slate-600",
};

/** Hex colour for risk level (used in MapLibre paint expressions) */
export const riskHex = {
  LOW:      "#22c55e",
  MODERATE: "#eab308",
  HIGH:     "#f97316",
  CRITICAL: "#ef4444",
  UNKNOWN:  "#94a3b8",
};

/**
 * MapLibre step expression: colour route lines by anti_shipping_score.
 * score ≥ 0.80 → green (optimal)
 * score ≥ 0.55 → yellow (moderate)
 * score  < 0.55 → orange (review needed)
 */
export const antiShippingLineColor = [
  "step",
  ["coalesce", ["get", "anti_shipping_score"], 0],
  "#94a3b8",          // default: slate (no score)
  0.01, "#f97316",    // 0.01–0.55: orange
  0.55, "#eab308",    // 0.55–0.80: yellow
  0.80, "#22c55e",    // 0.80+:     green
];

/** Human-readable label for an anti-shipping score */
export const antiShippingLabel = (score) => {
  if (score === null || score === undefined) return "—";
  if (score >= 0.80) return "Optimal";
  if (score >= 0.55) return "Moderate";
  return "Review";
};

/** Colour a raw numeric score 0–1 → hex */
export const scoreToHex = (score) => {
  if (!score && score !== 0) return riskHex.UNKNOWN;
  if (score >= 0.80) return riskHex.LOW;
  if (score >= 0.55) return riskHex.MODERATE;
  if (score >= 0.25) return riskHex.HIGH;
  return riskHex.CRITICAL;
};

