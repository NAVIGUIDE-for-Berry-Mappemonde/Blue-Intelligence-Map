/**
 * Registre des fonds de carte.
 *
 * `raster` = L.tileLayer classique (Esri Canvas) ; `gl` = carte marine
 * vectorielle Open Waters: Seamap rendue par MapLibre GL (chargé à la
 * demande via maplibre-gl-leaflet — licence ISC, maplibre-gl BSD-3-Clause,
 * pmtiles BSD-3-Clause ; on ne dépend PAS du package npm @openwaters/seamap,
 * GPL-3.0 — on consomme le style servi, licencié CC-BY 4.0).
 *
 * `REACT_APP_SEAMAP_STYLE_URL` pointe vers le miroir auto-hébergé en
 * production (voir infra/vps/seamap/) ; par défaut, le style public.
 */
import { TILE_URLS } from "./constants";

export const SEAMAP_STYLE_URL =
  process.env.REACT_APP_SEAMAP_STYLE_URL ||
  "https://tiles.openwaters.io/seamap/style.json";

export const BASEMAPS = {
  dark: {
    kind: "raster",
    url: TILE_URLS.dark,
    attribution: "&copy; Esri &copy; OpenStreetMap contributors",
  },
  light: {
    kind: "raster",
    url: TILE_URLS.light,
    attribution: "&copy; Esri &copy; OpenStreetMap contributors",
  },
  sea: {
    kind: "gl",
    styleUrl: SEAMAP_STYLE_URL,
    attribution:
      '© <a href="https://openwaters.io/charts/seamap" target="_blank" rel="noreferrer">Open Waters: Seamap</a> (CC-BY 4.0) '
      + "· © OpenStreetMap contributors · © Mapterhorn · Seascape",
    notForNavigation: true,
  },
};

export const BASEMAP_CYCLE = ["dark", "light", "sea"];

export function nextBasemap(current) {
  const idx = BASEMAP_CYCLE.indexOf(current);
  return BASEMAP_CYCLE[(idx + 1) % BASEMAP_CYCLE.length];
}

/**
 * Le style Seamap référence une source `elevation` (hillshade Versatiles)
 * souvent absente : chaque tuile 404 pollue la console sans rien dessiner.
 * On retire source + couches, le reste du style est inchangé.
 */
export const SEAMAP_OPTIONAL_SOURCES = ["elevation"];

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
