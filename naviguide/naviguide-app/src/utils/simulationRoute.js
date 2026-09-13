import { featuresToSegments } from "./geo.js";
import { waypointsFromCollection } from "./waypointsFromCollection.js";

const FALLBACK_START = { lat: 46.1541, lon: -1.167 };

/** Chaque waypoint de la route perso est une escale (le bateau s’y arrête). */
export function stopsFromCustomRoute(geojson) {
  return waypointsFromCollection(geojson).map((p) => ({
    name: p.name,
    lat: p.lat,
    lon: p.lon,
    flag: true,
  }));
}

/**
 * Si 1 LineString = 1 jambe entre deux waypoints, nomme from/to.
 * Sinon laisse les noms vides : useLegContext s’appuie sur les stops.
 */
export function namedSegments(segments, stops) {
  if (!Array.isArray(segments) || !segments.length) return [];
  if (!Array.isArray(stops) || stops.length < 2 || segments.length !== stops.length - 1) {
    return segments;
  }
  return segments.map((seg, i) => ({
    ...seg,
    from: { ...(seg.from || {}), name: stops[i].name, lat: stops[i].lat, lon: stops[i].lon },
    to: {
      ...(seg.to || {}),
      name: stops[i + 1].name,
      lat: stops[i + 1].lat,
      lon: stops[i + 1].lon,
    },
  }));
}

export function activeSimulationStops(customRoute, berryStops) {
  if (customRoute) return stopsFromCustomRoute(customRoute);
  return berryStops || [];
}

export function activeSimulationSegments(customRoute, berrySegments) {
  if (customRoute) {
    return namedSegments(featuresToSegments(customRoute), stopsFromCustomRoute(customRoute));
  }
  return berrySegments || [];
}

/**
 * Cibles Suivant/Précédent : départ, puis milieu et fin de chaque tronçon maritime.
 * [départ, mid0, end0, mid1, end1, …]
 */
export function buildSimTargets(segments, fallbackStops = []) {
  const maritimeSegs = (segments || []).filter((s) => !s.nonMaritime && s.coords?.length >= 2);
  if (maritimeSegs.length === 0) {
    const stops = (fallbackStops || []).filter(
      (p) => Number.isFinite(p?.lat) && Number.isFinite(p?.lon),
    );
    if (stops.length) return stops.map((p) => ({ lat: p.lat, lon: p.lon }));
    return [{ lat: FALLBACK_START.lat, lon: FALLBACK_START.lon }];
  }

  const firstCoord = maritimeSegs[0].coords[0];
  const list = [{ lat: firstCoord[1], lon: firstCoord[0] }];
  for (const seg of maritimeSegs) {
    const coords = seg.coords;
    let totalLen = 0;
    const lengths = [];
    for (let i = 0; i < coords.length - 1; i += 1) {
      const l = Math.hypot(coords[i + 1][0] - coords[i][0], coords[i + 1][1] - coords[i][1]);
      lengths.push(l);
      totalLen += l;
    }
    const halfLen = totalLen / 2;
    let acc = 0;
    let mid = null;
    for (let i = 0; i < lengths.length; i += 1) {
      if (acc + lengths[i] >= halfLen) {
        const t = lengths[i] > 0 ? (halfLen - acc) / lengths[i] : 0;
        mid = {
          lat: coords[i][1] + t * (coords[i + 1][1] - coords[i][1]),
          lon: coords[i][0] + t * (coords[i + 1][0] - coords[i][0]),
        };
        break;
      }
      acc += lengths[i];
    }
    if (!mid) {
      const m = Math.floor(coords.length / 2);
      mid = { lat: coords[m][1], lon: coords[m][0] };
    }
    const last = coords[coords.length - 1];
    list.push(mid);
    list.push({ lat: last[1], lon: last[0] });
  }
  return list;
}

export function simulationStartPos(targets, fallback = FALLBACK_START) {
  const first = targets?.[0];
  if (first && Number.isFinite(first.lat) && Number.isFinite(first.lon)) {
    return { lat: first.lat, lon: first.lon };
  }
  return fallback;
}
