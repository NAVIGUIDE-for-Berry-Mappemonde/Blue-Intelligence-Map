export function kindFromLayer(layerId) {
  if (layerId === "bi-projects-circle") return "project";
  if (layerId === "bi-marinas-circle") return "marina";
  if (layerId === "bi-capitaineries-circle") return "capitainerie";
  if (layerId === "bi-poe-circle") return "poe";
  if (layerId === "bi-amp-fill") return "amp";
  if (layerId === "ports-circle") return "port";
  return null;
}

export const BI_CLICK_LAYERS = [
  "bi-projects-circle",
  "bi-marinas-circle",
  "bi-capitaineries-circle",
  "bi-poe-circle",
  "bi-amp-fill",
  "ports-circle",
];

export function featureContains(feature, lon, lat) {
  const g = feature?.geometry;
  if (!g) return false;
  const rings = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : null;
  if (!rings) return false;
  return rings.some((poly) => ringContains(poly[0], lon, lat));
}

function ringContains(ring, lon, lat) {
  if (!ring?.length) return false;
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const intersect = ((yi > lat) !== (yj > lat)) && (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}
