/**
 * Vent climatologique pour l'ETA NAVIGUIDE.
 *
 * Repli zones (même logique que climatology.py) tant que l'atlas CMEMS
 * n'est pas chargé côté client. Ce n'est PAS une prévision.
 * kind: climatology.
 */

function interp(v, v0, v1, r0, r1) {
  if (v1 === v0) return r0;
  const t = Math.max(0, Math.min(1, (v - v0) / (v1 - v0)));
  return r0 + t * (r1 - r0);
}

/**
 * @returns {{ speedKnots: number, dirFromDeg: number, source: string }}
 */
export function zoneWindAt(lat, lon, month) {
  const m = Math.max(1, Math.min(12, Number(month) || 1));
  if (lat > 60) return { speedKnots: 18 + 4 * Math.sin((m * 30 * Math.PI) / 180), dirFromDeg: 240, source: "zone_fallback" };
  if (lat < -60) return { speedKnots: 28 + 5 * Math.sin((m * 30 * Math.PI) / 180), dirFromDeg: 270, source: "zone_fallback" };

  const inAtlantic = lon >= -80 && lon <= 20;
  const inIndian = lon >= 20 && lon <= 120;
  const inPacific = lon >= 120 || lon <= -80;
  const inMed = lon >= -10 && lon <= 40 && lat >= 30 && lat <= 47;

  if (inMed) {
    if ([6, 7, 8].includes(m)) return { speedKnots: 14, dirFromDeg: 340, source: "zone_fallback" };
    if ([12, 1, 2].includes(m)) return { speedKnots: 16, dirFromDeg: 220, source: "zone_fallback" };
    return { speedKnots: 10, dirFromDeg: 300, source: "zone_fallback" };
  }
  if (inAtlantic && lat >= 25 && lat <= 40) {
    return [6, 7, 8, 9].includes(m)
      ? { speedKnots: 10, dirFromDeg: 260, source: "zone_fallback" }
      : { speedKnots: 14, dirFromDeg: 240, source: "zone_fallback" };
  }
  if (inAtlantic && lat >= 5 && lat <= 25) {
    let spd = 15;
    if ([12, 1, 2, 3].includes(m)) spd = 18;
    else if ([6, 7, 8, 9].includes(m)) spd = 12;
    return { speedKnots: spd, dirFromDeg: 50, source: "zone_fallback" };
  }
  if (inAtlantic && lat >= -25 && lat <= 5) {
    return { speedKnots: [6, 7, 8].includes(m) ? 16 : 13, dirFromDeg: 130, source: "zone_fallback" };
  }
  if (inAtlantic && lat >= -50 && lat <= -25) {
    return { speedKnots: 20 + 5 * interp(lat, -25, -50, 0, 1), dirFromDeg: 270, source: "zone_fallback" };
  }
  if (inIndian && lat >= 5) {
    if ([6, 7, 8, 9].includes(m)) return { speedKnots: 20, dirFromDeg: 225, source: "zone_fallback" };
    if ([12, 1, 2, 3].includes(m)) return { speedKnots: 14, dirFromDeg: 45, source: "zone_fallback" };
    return { speedKnots: 8, dirFromDeg: 90, source: "zone_fallback" };
  }
  if (inIndian && lat >= -25 && lat <= 5) {
    return { speedKnots: [6, 7, 8].includes(m) ? 17 : 13, dirFromDeg: 135, source: "zone_fallback" };
  }
  if (inIndian && lat >= -60 && lat <= -25) {
    return { speedKnots: 22 + 8 * interp(lat, -25, -60, 0, 1), dirFromDeg: 270, source: "zone_fallback" };
  }
  if (inPacific && lat >= 5 && lat <= 25) {
    let spd = 14;
    if ([12, 1, 2, 3].includes(m)) spd = 17;
    else if ([7, 8, 9].includes(m)) spd = 12;
    return { speedKnots: spd, dirFromDeg: 55, source: "zone_fallback" };
  }
  if (inPacific && lat >= -30 && lat <= 5) {
    return { speedKnots: [6, 7, 8, 9].includes(m) ? 16 : 13, dirFromDeg: 120, source: "zone_fallback" };
  }
  if (inPacific && lat >= 35 && lat <= 60) {
    return { speedKnots: [12, 1, 2, 3].includes(m) ? 25 : 16, dirFromDeg: 260, source: "zone_fallback" };
  }
  if (inPacific && lat >= -60 && lat <= -30) {
    return { speedKnots: 20 + 7 * interp(lat, -30, -60, 0, 1), dirFromDeg: 270, source: "zone_fallback" };
  }
  if (inAtlantic && lat >= 40 && lat <= 60) {
    return { speedKnots: [12, 1, 2].includes(m) ? 22 : 15, dirFromDeg: 255, source: "zone_fallback" };
  }
  if (Math.abs(lat) <= 8) {
    const itcz = 5 * Math.sin(((m - 7) * 30 * Math.PI) / 180);
    if (Math.abs(lat - itcz) < 4) return { speedKnots: 4, dirFromDeg: 200, source: "zone_fallback" };
  }
  if (lat >= -60 && lat <= -40) {
    return { speedKnots: 25 + 5 * interp(lat, -40, -60, 0, 1), dirFromDeg: 275, source: "zone_fallback" };
  }
  return { speedKnots: 10, dirFromDeg: 270, source: "zone_fallback" };
}

/**
 * Polar catamaran très simple : ~0.45 × TWS au reaching, borné 4–11 kn.
 * Suffit pour qu'un ETA bouge avec le mois sans allumer une couche.
 */
export function boatSpeedFromWind(windKnots) {
  const raw = Number(windKnots) * 0.45;
  return Math.round(Math.max(4, Math.min(11, raw)) * 10) / 10;
}

export function boatSpeedFromClimatology(lat, lon, month) {
  const wind = zoneWindAt(lat, lon, month);
  return {
    speedKnots: boatSpeedFromWind(wind.speedKnots),
    windKnots: Math.round(wind.speedKnots * 10) / 10,
    dirFromDeg: wind.dirFromDeg,
    source: wind.source,
    month,
    kind: "climatology",
  };
}
