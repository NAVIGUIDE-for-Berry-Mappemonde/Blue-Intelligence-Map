/**
 * Waypoints nommés pour l'orchestrateur et le briefing local.
 * Points d'abord ; si moins de 2, extrait départ/arrivée des LineString
 * (fichiers GeoJSON/KML souvent sans Point).
 */
export function waypointsFromCollection(geojson) {
  const wps = [];
  for (const f of geojson?.features || []) {
    if (f?.geometry?.type !== "Point" || !Array.isArray(f.geometry.coordinates)) continue;
    const lon = Number(f.geometry.coordinates[0]);
    const lat = Number(f.geometry.coordinates[1]);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    wps.push({
      name: f.properties?.name || `Point ${wps.length + 1}`,
      lat,
      lon,
      mandatory: true,
    });
  }
  if (wps.length < 2) {
    for (const f of geojson?.features || []) {
      if (f?.geometry?.type !== "LineString" || !f.geometry.coordinates?.length) continue;
      const c = f.geometry.coordinates;
      if (!wps.length) {
        wps.push({ name: "Départ", lat: c[0][1], lon: c[0][0], mandatory: true });
      }
      const last = c[c.length - 1];
      wps.push({
        name: `Escale ${wps.length}`,
        lat: last[1],
        lon: last[0],
        mandatory: true,
      });
    }
  }
  return wps;
}
