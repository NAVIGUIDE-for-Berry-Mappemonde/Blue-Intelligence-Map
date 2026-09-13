import { featuresToSegments, haversineNm, summarizeRoute } from "./geo.js";
import { waypointsFromCollection } from "./waypointsFromCollection.js";

/**
 * Briefing de secours quand l'orchestrateur est injoignable.
 * Décrit uniquement la GeoJSON affichée — jamais le trajet Berry.
 */
export function buildLocalCustomBriefing(geojson, language = "fr") {
  const wps = waypointsFromCollection(geojson);
  const { nm, segments } = summarizeRoute(featuresToSegments(geojson));
  if (wps.length < 2 && segments < 1) return null;

  let dist = Math.round(nm);
  if (dist === 0 && wps.length >= 2) {
    let h = 0;
    for (let i = 1; i < wps.length; i += 1) {
      h += haversineNm(wps[i - 1].lat, wps[i - 1].lon, wps[i].lat, wps[i].lon);
    }
    dist = Math.round(h);
  }

  const pts = wps.length;
  const segs = segments || Math.max(0, pts - 1);
  const fr = language !== "en";
  const trail = wps
    .map((p) => {
      const lat = `${Math.abs(p.lat).toFixed(2)}°${p.lat >= 0 ? "N" : "S"}`;
      const lon = `${Math.abs(p.lon).toFixed(2)}°${p.lon >= 0 ? "E" : "W"}`;
      return `${p.name} (${lat}, ${lon})`;
    })
    .join(" → ");

  const summary = fr
    ? `Route personnalisée — ${pts || segs + 1} points, ${segs} segment${segs > 1 ? "s" : ""}, environ ${dist} NM.`
    : `Custom route — ${pts || segs + 1} points, ${segs} segment${segs > 1 ? "s" : ""}, about ${dist} NM.`;

  const narrative = fr
    ? `Cette route a été tracée à la main sur la carte. Elle ne suit pas le voyage par défaut de l'expédition. Distance estimée ${dist} milles nautiques sur ${segs} segment${segs > 1 ? "s" : ""}.${trail ? ` Waypoints : ${trail}.` : ""}`
    : `This route was drawn by hand on the map. It is not the default expedition voyage. Estimated distance ${dist} nautical miles over ${segs} segment${segs > 1 ? "s" : ""}.${trail ? ` Waypoints: ${trail}.` : ""}`;

  const note = fr
    ? "Résumé local : l'assistant de briefing n'a pas pu être joint."
    : "Local summary: the briefing assistant could not be reached.";

  return {
    executive_briefing: `${summary}\n\n${narrative}\n\n${note}`,
    summary,
    narrative,
    legs: [],
    localFallback: true,
  };
}
