/** Sources optionnelles du style Seamap (hillshade souvent 404). */
export const SEAMAP_OPTIONAL_SOURCES = ["elevation"];

export const SEAMAP_STYLE_CANDIDATES = [
  typeof import.meta !== "undefined" && import.meta.env?.VITE_SEAMAP_STYLE_URL,
  "/tiles/seamap/style.json",
  "https://blueintelligence.online/tiles/seamap/style.json",
  "https://tiles.openwaters.io/seamap/style.json",
].filter(Boolean);

export function stripUnavailableSources(style, drop = SEAMAP_OPTIONAL_SOURCES) {
  if (!style || typeof style !== "object") return style;
  const skip = new Set(drop);
  const next = { ...style };
  if (style.sources) {
    next.sources = { ...style.sources };
    skip.forEach((id) => { delete next.sources[id]; });
  }
  if (Array.isArray(style.layers)) {
    next.layers = style.layers.filter((l) => !skip.has(l.source));
  }
  return next;
}

export const SEAMAP_ATTRIBUTION =
  '© <a href="https://openwaters.io/charts/seamap" target="_blank" rel="noreferrer">Open Waters: Seamap</a> (CC-BY 4.0) · © OpenStreetMap contributors';
