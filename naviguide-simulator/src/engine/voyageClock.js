/**
 * Table d’horloge climatologique : vertex → date civile.
 * The searoute track does not move. kind: climatology. No GRIB.
 */

import { alongTrackSpeed } from "./alongTrackSpeed.js";
import { nameAirEpisodes } from "./filmCast.js";
import { bearingDeg } from "./routeWindProfile.js";

export const AIR_CALENDAR_HOURS = 8;
export const SAINT_MAUR_LAND_HOURS = 4;
export const MIN_BOAT_KNOTS = 0.5;
export const DEFAULT_T0_ISO = "2026-05-15T08:00:00.000Z";
export const DEFAULT_START_AT = "la-rochelle";
export const OFFICIAL_VOYAGE_ID = "berry-mappemonde-2026-officiel";

export const DEFAULT_PORT_DAYS = Object.freeze({
  laRochelle: 3,
  halifax: 1,
  saintMaur: 0,
  default: 3,
});

const MONTHS_SHORT = {
  fr: ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};

const MONTHS_LONG = {
  fr: ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
  en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
};

export function isoFromT0(t0, tHours) {
  const base = Date.parse(t0);
  const h = Number(tHours) || 0;
  if (!Number.isFinite(base)) return null;
  return new Date(base + h * 3600 * 1000).toISOString();
}

export function monthOfT0(t0, tHours) {
  const iso = isoFromT0(t0, tHours);
  if (!iso) return 1;
  return new Date(iso).getUTCMonth() + 1;
}

export function portHoldHours(name, portDays = DEFAULT_PORT_DAYS) {
  const n = String(name || "");
  if (/saint[- ]?maur/i.test(n)) return (portDays.saintMaur ?? 0) * 24;
  if (/la\s*rochelle/i.test(n)) return (portDays.laRochelle ?? 3) * 24;
  if (/halifax/i.test(n)) return (portDays.halifax ?? 1) * 24;
  return (portDays.default ?? 2) * 24;
}

function filmOf(p) {
  return p?.filmCum ?? p?.cumNm ?? 0;
}

function resolveSeaStart(marks, flat, startAt) {
  if (startAt === "saint-maur") {
    return { filmNm: 0, name: (marks || [])[0]?.name || "Saint-Maur" };
  }
  const lr = (marks || []).find((m) => /la\s*rochelle/i.test(m.name || ""));
  if (lr) return { filmNm: Number(lr.filmNm ?? lr.nm) || 0, name: lr.name };
  const pts = flat?.points || [];
  for (let i = 0; i < pts.length; i++) {
    if (!pts[i].nonMaritime && !pts[i].jump) {
      return { filmNm: filmOf(pts[i]), name: null, index: i };
    }
  }
  return { filmNm: 0, name: null };
}

function withHubMarks(marks, flat, stops) {
  const out = [...(marks || [])];
  const episodes = nameAirEpisodes(flat?.episodes || [], stops);
  for (const ep of episodes) {
    const hubP = flat.points?.[ep.ja];
    if (!hubP) continue;
    const filmNm = filmOf(hubP);
    if (out.some((m) => Math.abs((m.filmNm ?? m.nm) - filmNm) < 0.3)) continue;
    out.push({
      name: ep.hubName || "Halifax (Nouvelle-Écosse)",
      filmNm,
      nm: hubP.cumNm,
      lat: hubP.lat,
      lon: hubP.lon,
      index: ep.ja,
      kind: "hub",
    });
  }
  out.sort((a, b) => (a.filmNm ?? a.nm) - (b.filmNm ?? b.nm));
  return out;
}

function vehicleAt(points, index, episodes) {
  const p = points[index];
  if (!p) return "main";
  if (p.jump) return "plane";
  if (p.nonMaritime) return "land";
  for (const ep of episodes || []) {
    if (index > ep.ja && index < ep.jb) return "side";
  }
  return "main";
}

function markAtPoint(marks, index, point) {
  const film = filmOf(point);
  return (marks || []).find((m) => {
    if (Number.isInteger(m.index) && m.index === index) return true;
    return Math.abs((m.filmNm ?? m.nm) - film) < 0.2;
  }) || null;
}

function shouldHold(mark, seaStartFilmNm) {
  if (!mark) return false;
  const hold = portHoldHours(mark.name);
  if (!(hold > 0)) return false;
  const at = Number(mark.filmNm ?? mark.nm) || 0;
  if (Math.abs(at - seaStartFilmNm) < 0.25) return false;
  return true;
}

/**
 * @returns {object} table §7 du plan A
 */
export function buildVoyageClock({
  flat,
  marks = [],
  t0 = DEFAULT_T0_ISO,
  polarRaw = null,
  portDays = DEFAULT_PORT_DAYS,
  startAt = DEFAULT_START_AT,
  stops = [],
} = {}) {
  const points = flat?.points || [];
  const episodes = flat?.episodes || [];
  const clockMarksIn = withHubMarks(marks, flat, stops);
  const seaStart = resolveSeaStart(clockMarksIn, flat, startAt);
  const vertices = [];
  const outMarks = [];
  const usedMarks = new Set();

  let tHours = 0;
  let seaHours = 0;
  let quayHours = 0;
  let landBudgetUsed = false;

  const pushVertex = ({
    filmNm,
    sailNm,
    lat,
    lon,
    bearing,
    speedKnots,
    windKnots,
    twa,
    dirFromDeg,
    month,
    vehicle,
    kind = "climatology",
    model = null,
    leadHours = null,
    reason = null,
  }) => {
    vertices.push({
      filmNm,
      sailNm,
      lat,
      lon,
      bearing,
      tHours,
      iso: isoFromT0(t0, tHours),
      speedKnots,
      windKnots,
      twa,
      dirFromDeg: dirFromDeg ?? null,
      month,
      vehicle,
      seaHours,
      kind: kind || "climatology",
      model: model ?? null,
      leadHours: leadHours ?? null,
      reason: reason || null,
    });
  };

  const applyQuay = (mark, point, bearing) => {
    if (!mark || usedMarks.has(mark)) return;
    usedMarks.add(mark);
    const holdHours = shouldHold(mark, seaStart.filmNm)
      ? portHoldHours(mark.name, portDays)
      : 0;
    const arrivalHours = tHours;
    const arrivalIso = isoFromT0(t0, arrivalHours);
    outMarks.push({
      name: mark.name,
      filmNm: mark.filmNm ?? mark.nm ?? filmOf(point),
      tHours: arrivalHours,
      iso: arrivalIso,
      holdHours,
    });
    if (!(holdHours > 0)) return;
    quayHours += holdHours;
    tHours += holdHours;
    pushVertex({
      filmNm: filmOf(point),
      sailNm: point.cumNm,
      lat: point.lat,
      lon: point.lon,
      bearing,
      speedKnots: null,
      windKnots: null,
      twa: null,
      dirFromDeg: null,
      month: monthOfT0(t0, tHours),
      vehicle: "quay",
    });
  };

  if (!points.length) {
    return {
      t0,
      kind: "climatology",
      vertices: [],
      marks: [],
      seaHours: 0,
      quayHours: 0,
      arrivalIso: isoFromT0(t0, 0),
      startAt,
    };
  }

  const p0 = points[0];
  pushVertex({
    filmNm: filmOf(p0),
    sailNm: p0.cumNm ?? 0,
    lat: p0.lat,
    lon: p0.lon,
    bearing: points[1] ? bearingDeg(p0, points[1]) : 0,
    speedKnots: null,
    windKnots: null,
    twa: null,
    dirFromDeg: null,
    month: monthOfT0(t0, 0),
    vehicle: vehicleAt(points, 0, episodes),
  });
  applyQuay(markAtPoint(clockMarksIn, 0, p0), p0, vertices[0].bearing);

  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    const bearing = bearingDeg(a, b);
    const destVehicle = vehicleAt(points, i + 1, episodes);
    const month = monthOfT0(t0, tHours);
    let speedKnots = null;
    let windKnots = null;
    let twa = null;
    let dirFromDeg = null;
    let edgeKind = "climatology";
    let edgeModel = null;

    const landEdge = destVehicle === "land" || (a.nonMaritime && b.nonMaritime);
    const beforeSea = filmOf(b) < seaStart.filmNm - 0.05;
    if (b.jump || destVehicle === "plane") {
      tHours += AIR_CALENDAR_HOURS;
    } else if (landEdge || beforeSea) {
      if (startAt === "saint-maur" && !landBudgetUsed) {
        tHours += SAINT_MAUR_LAND_HOURS;
        landBudgetUsed = true;
      }
    } else {
      const spanNm = Math.max(0, (b.cumNm ?? 0) - (a.cumNm ?? 0));
      const along = alongTrackSpeed({
        lat: a.lat,
        lon: a.lon,
        bearing,
        month,
        polarRaw,
      });
      const knots = Math.max(MIN_BOAT_KNOTS, along.speedKnots || MIN_BOAT_KNOTS);
      const dt = spanNm / knots;
      tHours += dt;
      seaHours += dt;
      speedKnots = along.speedKnots;
      windKnots = along.windKnots;
      twa = along.twa;
      dirFromDeg = along.dirFromDeg;
      edgeKind = along.kind || "climatology";
      edgeModel = along.model || null;
    }

    pushVertex({
      filmNm: filmOf(b),
      sailNm: b.cumNm ?? 0,
      lat: b.lat,
      lon: b.lon,
      bearing,
      speedKnots,
      windKnots,
      twa,
      dirFromDeg,
      month: monthOfT0(t0, tHours),
      vehicle: destVehicle,
      kind: destVehicle === "plane" || destVehicle === "land" ? "climatology" : edgeKind,
      model: destVehicle === "plane" || destVehicle === "land" ? null : edgeModel,
    });
    applyQuay(markAtPoint(clockMarksIn, i + 1, b), b, bearing);
  }

  const lastSail = [...vertices].reverse().find((v) => v.vehicle !== "quay") || vertices.at(-1);
  return {
    t0,
    kind: "climatology",
    vertices,
    marks: outMarks,
    seaHours,
    quayHours,
    arrivalIso: lastSail?.iso || isoFromT0(t0, tHours),
    startAt,
  };
}

function lerpNum(a, b, t) {
  if (a == null || b == null) return a ?? b ?? null;
  return a + (b - a) * t;
}

function sampleFromVertex(clock, v, extra = {}) {
  return {
    ...v,
    iso: v.iso || isoFromT0(clock.t0, v.tHours),
    kind: v.kind || "climatology",
    model: v.model ?? null,
    leadHours: v.leadHours ?? null,
    atQuay: false,
    holdHours: 0,
    ...extra,
  };
}

/**
 * filmNm → date. At a stopover, atQuay=true returns departure (the date that jumps).
 */
export function lookupVoyageClock(clock, filmNm, { atQuay = false } = {}) {
  if (!clock?.vertices?.length) return null;
  const verts = clock.vertices;
  const x = Math.max(0, Number(filmNm) || 0);
  const mark = (clock.marks || []).find((m) => Math.abs((m.filmNm ?? m.nm) - x) <= 0.45);

  if (mark) {
    const pair = verts.filter((v) => Math.abs(v.filmNm - (mark.filmNm ?? mark.nm)) < 1e-4);
    const holdHours = mark.holdHours || 0;
    if (pair.length >= 2 && atQuay && holdHours > 0) {
      return sampleFromVertex(clock, pair[pair.length - 1], {
        atQuay: true,
        holdHours,
        markName: mark.name,
      });
    }
    if (pair.length) {
      return sampleFromVertex(clock, pair[0], {
        atQuay: false,
        holdHours,
        markName: mark.name,
      });
    }
  }

  let left = verts[0];
  let rightIdx = verts.length - 1;
  for (let i = 0; i < verts.length; i++) {
    if (verts[i].filmNm <= x + 1e-9) left = verts[i];
    if (verts[i].filmNm >= x - 1e-9) {
      rightIdx = i;
      break;
    }
  }
  let right = verts[rightIdx];
  if (right.filmNm <= left.filmNm + 1e-9) {
    return sampleFromVertex(clock, left);
  }
  const span = right.filmNm - left.filmNm;
  const t = Math.max(0, Math.min(1, (x - left.filmNm) / span));
  const tHours = lerpNum(left.tHours, right.tHours, t);
  const vehicle = t < 1 ? left.vehicle : right.vehicle;
  const airOrQuay = vehicle === "plane" || vehicle === "quay" || right.vehicle === "plane";
  return {
    filmNm: lerpNum(left.filmNm, right.filmNm, t),
    sailNm: lerpNum(left.sailNm, right.sailNm, t),
    lat: lerpNum(left.lat, right.lat, t),
    lon: lerpNum(left.lon, right.lon, t),
    bearing: left.bearing,
    tHours,
    iso: isoFromT0(clock.t0, tHours),
    speedKnots: airOrQuay ? right.speedKnots : lerpNum(left.speedKnots, right.speedKnots, t),
    windKnots: airOrQuay ? right.windKnots : lerpNum(left.windKnots, right.windKnots, t),
    twa: airOrQuay ? right.twa : lerpNum(left.twa, right.twa, t),
    dirFromDeg: left.dirFromDeg ?? right.dirFromDeg ?? null,
    month: monthOfT0(clock.t0, tHours),
    vehicle: airOrQuay ? (right.vehicle === "plane" || left.vehicle === "plane" ? "plane" : vehicle) : vehicle,
    seaHours: lerpNum(left.seaHours, right.seaHours, t),
    kind: (t < 0.5 ? left.kind : right.kind) || "climatology",
    model: right.model || left.model || null,
    leadHours: right.leadHours ?? left.leadHours ?? null,
    atQuay: false,
    holdHours: 0,
  };
}

/**
 * Horloge murale → position (mode Suivre, repli hors ligne).
 */
export function sampleClockAtHours(clock, tHours) {
  const verts = clock?.vertices || [];
  if (!verts.length) return null;
  const x = Number(tHours);
  if (x < 0) {
    return sampleFromVertex(clock, verts[0], {
      status: "waiting",
      atQuay: true,
      countdownHours: -x,
    });
  }
  if (x <= verts[0].tHours) {
    return sampleFromVertex(clock, verts[0], { status: "live", atQuay: false });
  }
  const last = verts[verts.length - 1];
  if (x >= last.tHours) {
    return sampleFromVertex(clock, last, {
      status: "arrived",
      atQuay: last.vehicle === "quay",
    });
  }
  for (let i = 0; i < verts.length - 1; i++) {
    const a = verts[i];
    const b = verts[i + 1];
    if (x > b.tHours) continue;
    const span = (b.tHours - a.tHours) || 1;
    const t = (x - a.tHours) / span;
    if (Math.abs((b.filmNm ?? 0) - (a.filmNm ?? 0)) < 1e-6) {
      return sampleFromVertex(clock, a, {
        tHours: x,
        iso: isoFromT0(clock.t0, x),
        atQuay: true,
        status: "live",
        vehicle: "quay",
      });
    }
    return {
      ...sampleFromVertex(clock, a, { status: "live" }),
      lat: lerpNum(a.lat, b.lat, t),
      lon: lerpNum(a.lon, b.lon, t),
      filmNm: lerpNum(a.filmNm, b.filmNm, t),
      sailNm: lerpNum(a.sailNm, b.sailNm, t),
      tHours: x,
      iso: isoFromT0(clock.t0, x),
      seaHours: lerpNum(a.seaHours, b.seaHours, t),
      kind: (t < 0.5 ? a.kind : b.kind) || "climatology",
      model: b.model || a.model || null,
      leadHours: b.leadHours ?? a.leadHours ?? null,
      speedKnots: b.speedKnots ?? a.speedKnots,
      windKnots: b.windKnots ?? a.windKnots,
    };
  }
  return sampleFromVertex(clock, last, { status: "arrived" });
}

export function sampleClockAtTime(clock, when) {
  if (!clock?.t0) return null;
  const t0 = Date.parse(clock.t0);
  const w = when instanceof Date ? when.getTime() : Date.parse(when);
  if (!Number.isFinite(t0) || !Number.isFinite(w)) return null;
  return sampleClockAtHours(clock, (w - t0) / 3600000);
}

export function etaHoursToFilmNm(clock, fromFilmNm, toFilmNm, { atQuay = false } = {}) {
  const here = lookupVoyageClock(clock, fromFilmNm, { atQuay });
  const dest = lookupVoyageClock(clock, toFilmNm, { atQuay: false });
  if (!here || !dest) return null;
  return Math.max(0, dest.tHours - here.tHours);
}

export function clockWindSeries(clock, { maxPoints = 24 } = {}) {
  const verts = (clock?.vertices || []).filter(
    (v) => (v.vehicle === "main" || v.vehicle === "side") && Number.isFinite(Number(v.windKnots)),
  );
  if (!verts.length) return [];
  const pick = [];
  if (verts.length <= maxPoints) {
    pick.push(...verts);
  } else {
    for (let i = 0; i < maxPoints; i++) {
      const idx = Math.round((i * (verts.length - 1)) / (maxPoints - 1));
      pick.push(verts[idx]);
    }
  }
  return pick.map((v) => ({
    filmNm: v.filmNm,
    cumNm: v.sailNm,
    lat: v.lat,
    lon: v.lon,
    tws: v.windKnots,
    boatKnots: v.speedKnots,
    heading: v.bearing,
    windFrom: v.dirFromDeg,
  }));
}

export function formatCivilDate(iso, lang = "fr") {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const months = MONTHS_SHORT[lang] || MONTHS_SHORT.fr;
  const day = d.getUTCDate();
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${day} ${months[d.getUTCMonth()]} ${hh}:${mm} UTC`;
}

export function formatMonthName(month, lang = "fr") {
  const m = Math.max(1, Math.min(12, Number(month) || 1));
  const months = MONTHS_LONG[lang] || MONTHS_LONG.fr;
  return months[m - 1];
}

/** Graduations barre = la même horloge (pas un 2ᵉ compteur nm/j). */
export function clockTickLabelsFromClock(clock, lang = "fr") {
  if (!clock?.vertices?.length) return [];
  const last = clock.vertices[clock.vertices.length - 1];
  const maxFilm = Number(last.filmNm) || 0;
  if (maxFilm <= 0) return [];
  return [0, 0.5, 1].map((frac) => {
    const sample = lookupVoyageClock(clock, maxFilm * frac);
    const sail = Math.round(Number(sample?.sailNm) || 0);
    const days = Math.max(0, Math.floor((Number(sample?.seaHours) || 0) / 24));
    const loc = lang === "en" ? "en-US" : "fr-FR";
    return {
      filmNm: maxFilm * frac,
      label: `${sail.toLocaleString(loc)} nm · j${days}`,
    };
  });
}

export function formatFilmClockLine({ sailNm, seaHours, iso, lang = "fr" }) {
  const days = Math.max(0, Math.floor((Number(seaHours) || 0) / 24));
  const nm = Math.round(Number(sailNm) || 0).toLocaleString(lang === "en" ? "en-US" : "fr-FR");
  const dayLabel = lang === "en" ? `d${days}` : `j${days}`;
  return `${nm} nm · ${dayLabel} · ${formatCivilDate(iso, lang)}`;
}

export function parseDepartureUtc(dateStr, timeStr) {
  const d = String(dateStr || "").trim();
  const tm = String(timeStr || "08:00").trim() || "08:00";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return DEFAULT_T0_ISO;
  const hhmm = /^\d{2}:\d{2}$/.test(tm) ? tm : "08:00";
  return `${d}T${hhmm}:00.000Z`;
}

export function splitDepartureUtc(iso) {
  const fallback = { date: "2026-05-15", time: "08:00" };
  const v = String(iso || "");
  if (v.length < 16) return fallback;
  return { date: v.slice(0, 10), time: v.slice(11, 16) };
}
