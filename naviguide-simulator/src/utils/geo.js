/** Rayon terrestre en milles nautiques. */
export const R_NM = 3440.065;

export function toRad(deg) {
  return (deg * Math.PI) / 180;
}

export function wrapLon(lon) {
  if (!Number.isFinite(lon)) return lon;
  let x = lon;
  while (x > 180) x -= 360;
  while (x < -180) x += 360;
  return x;
}

/** Unwrap longitudes so the track does not cross the map at 180°. */
export function unwrapLon(prevLon, lon) {
  if (!Number.isFinite(lon)) return lon;
  if (!Number.isFinite(prevLon)) return lon;
  let x = lon;
  while (x - prevLon > 180) x -= 360;
  while (x - prevLon < -180) x += 360;
  return x;
}

export function haversineNm(lat1, lon1, lat2, lon2) {
  const dLat = toRad(lat2 - lat1);
  let dLonDeg = lon2 - lon1;
  while (dLonDeg > 180) dLonDeg -= 360;
  while (dLonDeg < -180) dLonDeg += 360;
  const dLon = toRad(dLonDeg);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R_NM * Math.asin(Math.sqrt(a));
}

/** Split a [lon,lat] polyline at ±180° (otherwise Leaflet draws across the globe). */
export function splitAntimeridianCoords(coords) {
  const parts = [[]];
  for (const c of coords || []) {
    if (!c || !Number.isFinite(c[0]) || !Number.isFinite(c[1])) continue;
    const part = parts[parts.length - 1];
    if (part.length) {
      const prev = part[part.length - 1];
      if (Math.abs(c[0] - prev[0]) > 180) {
        parts.push([c]);
        continue;
      }
    }
    part.push(c);
  }
  return parts.filter((p) => p.length >= 2);
}

/** Copies ±360° pour que le tour du monde reste visible (Afrique + Pacifique). */
export function worldCopyCoords(coords) {
  if (!coords || coords.length < 2) return [];
  return [
    coords,
    coords.map(([lon, lat]) => [lon + 360, lat]),
    coords.map(([lon, lat]) => [lon - 360, lat]),
  ];
}

/** Triple chaque polyligne (monde 0 / +360 / −360). */
export function worldCopyParts(parts) {
  const out = [];
  for (const coords of parts || []) {
    out.push(...worldCopyCoords(coords));
  }
  return out;
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
