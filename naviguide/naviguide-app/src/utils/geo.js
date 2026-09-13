/** Rayon terrestre en milles nautiques. */
export const R_NM = 3440.065;

export function toRad(deg) {
  return (deg * Math.PI) / 180;
}

export function haversineNm(lat1, lon1, lat2, lon2) {
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R_NM * Math.asin(Math.sqrt(a));
}

/**
 * Distance nautique + nombre de segments d'une liste de polylignes
 * `segments` : [{ coords: [[lon, lat], ...] }]
 */
export function summarizeRoute(segments) {
  let nm = 0;
  let count = 0;
  if (!segments?.length) return { nm: 0, segments: 0 };
  for (const seg of segments) {
    const coords = seg?.coords;
    if (!coords || coords.length < 2) continue;
    count += 1;
    for (let i = 0; i < coords.length - 1; i++) {
      nm += haversineNm(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0]);
    }
  }
  return { nm: Math.round(nm * 10) / 10, segments: count };
}

/** FeatureCollection LineString → segments { coords } pour summarizeRoute / export. */
export function featuresToSegments(fc) {
  if (!fc?.features) return [];
  return fc.features
    .filter((f) => f?.geometry?.type === "LineString" && f.geometry.coordinates?.length >= 2)
    .map((f) => ({
      coords: f.geometry.coordinates,
      from: { name: f.properties?.from || f.properties?.name || "" },
      to: { name: f.properties?.to || "" },
      nonMaritime: false,
    }));
}
