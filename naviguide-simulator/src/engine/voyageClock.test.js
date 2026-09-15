import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { flattenRoute, mapEscalesOnRoute } from "./routePlayhead.js";
import {
  AIR_CALENDAR_HOURS,
  DEFAULT_PORT_DAYS,
  DEFAULT_T0_ISO,
  OFFICIAL_VOYAGE_ID,
  SAINT_MAUR_LAND_HOURS,
  buildVoyageClock,
  clockTickLabelsFromClock,
  formatFilmClockLine,
  lookupVoyageClock,
  parseDepartureUtc,
  portHoldHours,
  sampleClockAtTime,
  splitDepartureUtc,
} from "./voyageClock.js";

const CAYENNE = [-52.3533, 4.9333];
const HALIFAX = [-63.5652, 44.6488];
const SPM = [-56.1628, 46.7761];

function atlanticFlat() {
  return flattenRoute([
    { nonMaritime: true, coords: [[1.6358, 46.8075], [-1.167, 46.1541]] },
    {
      nonMaritime: false,
      coords: [
        [-1.167, 46.1541],
        [-12, 35],
        [-20, 25],
        [-25, 15],
        [-40, 14.8],
        [-55, 14.7],
        [-61.0731, 14.5887],
      ],
    },
  ]);
}

function atlanticMarks(flat) {
  return mapEscalesOnRoute([
    { name: "Saint-Maur (Berry, Indre)", lat: 46.8075, lon: 1.6358, flag: "f" },
    { name: "La Rochelle", lat: 46.1541, lon: -1.167, flag: "f" },
    { name: "Fort-de-France (Martinique)", lat: 14.5887, lon: -61.0731, flag: "f" },
  ], flat);
}

function clockFor(t0, extras = {}) {
  const flat = atlanticFlat();
  const marks = atlanticMarks(flat);
  return {
    flat,
    marks,
    clock: buildVoyageClock({
      flat,
      marks,
      t0,
      polarRaw: null,
      startAt: "la-rochelle",
      ...extras,
    }),
  };
}

function fdfMark(clock) {
  return clock.marks.find((m) => /Fort-de-France/i.test(m.name));
}

describe("voyageClock Atlantique", () => {
  it("March vs July, same nm: Fort-de-France arrivalIso differs", () => {
    const mar = clockFor("2026-03-15T08:00:00.000Z").clock;
    const jul = clockFor("2026-07-15T08:00:00.000Z").clock;
    assert.equal(mar.kind, "climatology");
    assert.equal(jul.kind, "climatology");
    const a = fdfMark(mar);
    const b = fdfMark(jul);
    assert.ok(a && b);
    assert.notEqual(a.iso, b.iso);
    const gapH = Math.abs(Date.parse(a.iso) - Date.parse(b.iso)) / 3600000;
    assert.ok(gapH > 48, `écart Fort-de-France ${gapH} h`);
  });

  it("t0 = 15 June 08:00, La Rochelle → Fort-de-France departure > 15 June", () => {
    const { clock } = clockFor("2026-06-15T08:00:00.000Z");
    const fdf = fdfMark(clock);
    assert.ok(fdf);
    assert.ok(Date.parse(fdf.iso) > Date.parse("2026-06-15T08:00:00.000Z"));
  });

  it("without polar: climatology source, no crash", () => {
    const { clock } = clockFor("2026-06-01T08:00:00.000Z");
    assert.equal(clock.kind, "climatology");
    assert.ok(clock.vertices.length > 3);
    assert.ok(clock.vertices.every((v) => Number.isFinite(v.tHours)));
    const sea = clock.vertices.find((v) => v.vehicle === "main" && v.speedKnots > 0);
    assert.ok(sea);
    assert.equal(sea.kind, "climatology");
    assert.ok("model" in sea);
    assert.ok("leadHours" in sea);
  });

  it("sampleClockAtTime: waiting if now < t0", () => {
    const { clock } = clockFor("2026-06-15T08:00:00.000Z");
    const waiting = sampleClockAtTime(clock, "2026-06-14T08:00:00.000Z");
    assert.equal(waiting.status, "waiting");
    assert.ok(waiting.countdownHours > 23);
    const live = sampleClockAtTime(clock, "2026-06-15T20:00:00.000Z");
    assert.equal(live.status, "live");
    assert.equal(live.kind, "climatology");
  });
});

describe("voyageClock quais et hops", () => {
  it("2-day quay: 48 h gap in iso at constant filmNm", () => {
    const flat = flattenRoute([
      { coords: [[-1.2, 46.1], [-20, 20], [-40, 15]] },
    ]);
    const marks = [
      { name: "La Rochelle", lat: 46.1, lon: -1.2, nm: 0, filmNm: 0, index: 0 },
      { name: "Escale Test", lat: 20, lon: -20, nm: flat.points[1].cumNm, filmNm: flat.points[1].filmCum, index: 1 },
      { name: "Fort-de-France (Martinique)", lat: 15, lon: -40, nm: flat.totalNm, filmNm: flat.totalFilmNm, index: flat.points.length - 1 },
    ];
    const clock = buildVoyageClock({
      flat,
      marks,
      t0: "2026-06-01T08:00:00.000Z",
      polarRaw: null,
      startAt: "la-rochelle",
      portDays: { laRochelle: 0, saintMaur: 0, halifax: 0, default: 2 },
    });
    const mid = clock.marks.find((m) => m.name === "Escale Test");
    assert.ok(mid);
    assert.equal(mid.holdHours, 48);
    const pair = clock.vertices.filter((v) => Math.abs(v.filmNm - mid.filmNm) < 1e-6);
    assert.ok(pair.length >= 2);
    const gap = pair[pair.length - 1].tHours - pair[0].tHours;
    assert.ok(Math.abs(gap - 48) < 1e-6);
    const arrival = lookupVoyageClock(clock, mid.filmNm, { atQuay: false });
    const leave = lookupVoyageClock(clock, mid.filmNm, { atQuay: true });
    assert.ok(Math.abs(leave.tHours - arrival.tHours - 48) < 1e-6);
    assert.equal(arrival.filmNm, leave.filmNm);
  });

  it("air hop: +8 h, speedKnots null", () => {
    const flat = flattenRoute([
      { coords: [[-52.36, 4.92], CAYENNE] },
      { coords: [HALIFAX, SPM] },
    ]);
    const clock = buildVoyageClock({
      flat,
      marks: [],
      t0: "2026-06-01T08:00:00.000Z",
      polarRaw: null,
      startAt: "la-rochelle",
    });
    const plane = clock.vertices.find((v) => v.vehicle === "plane");
    assert.ok(plane);
    assert.equal(plane.speedKnots, null);
    const before = clock.vertices[clock.vertices.indexOf(plane) - 1];
    assert.ok(Math.abs(plane.tHours - before.tHours - AIR_CALENDAR_HOURS) < 1e-6);
  });

  it("startAt saint-maur: first dt without a polar", () => {
    const { clock } = clockFor("2026-06-01T08:00:00.000Z", { startAt: "saint-maur" });
    const lr = clock.marks.find((m) => /La Rochelle/i.test(m.name));
    assert.ok(lr);
    assert.ok(Math.abs(lr.tHours - SAINT_MAUR_LAND_HOURS) < 1e-6);
    const land = clock.vertices.find((v) => v.vehicle === "land" && v.filmNm > 0);
    assert.ok(land);
    assert.equal(land.speedKnots, null);
  });
});

describe("voyageClock antimeridian", () => {
  it("tHours is monotonic across the antimeridian", () => {
    const flat = flattenRoute([
      { coords: [[179.2, -15], [179.8, -15], [-179.8, -15], [-179.2, -15]] },
    ]);
    const clock = buildVoyageClock({
      flat,
      marks: [],
      t0: "2026-06-01T08:00:00.000Z",
      polarRaw: null,
      startAt: "la-rochelle",
    });
    let prev = -1;
    for (const v of clock.vertices) {
      assert.ok(v.tHours >= prev - 1e-9, `tHours ${v.tHours} < ${prev}`);
      prev = v.tHours;
    }
    assert.ok(clock.vertices.at(-1).tHours > 0);
  });
});

describe("voyageClock contrat B0", () => {
  it("each vertex carries kind + seaHours (same schema as the server)", () => {
    const { clock } = clockFor("2026-06-15T08:00:00.000Z");
    const keys = [
      "filmNm", "sailNm", "lat", "lon", "bearing", "tHours", "iso",
      "speedKnots", "windKnots", "twa", "month", "vehicle", "kind", "seaHours",
    ];
    assert.ok(clock.vertices.length > 0);
    for (const k of keys) {
      assert.ok(k in clock.vertices[0], `manque ${k}`);
    }
    assert.ok(clock.vertices.every((v) => v.kind === "climatology"));
  });
});

describe("parseDepartureUtc", () => {
  it("compose un ISO UTC depuis date + heure", () => {
    assert.equal(parseDepartureUtc("2026-03-15", "08:00"), "2026-03-15T08:00:00.000Z");
    assert.deepEqual(splitDepartureUtc("2026-06-01T08:00:00.000Z"), { date: "2026-06-01", time: "08:00" });
  });
});

describe("U0 horloge officielle", () => {
  it("t0 = 15 mai 2026 08:00 UTC, pas le 1er juin", () => {
    assert.equal(DEFAULT_T0_ISO, "2026-05-15T08:00:00.000Z");
    assert.equal(OFFICIAL_VOYAGE_ID, "berry-mappemonde-2026-officiel");
    assert.deepEqual(splitDepartureUtc(DEFAULT_T0_ISO), { date: "2026-05-15", time: "08:00" });
    assert.deepEqual(splitDepartureUtc(""), { date: "2026-05-15", time: "08:00" });
  });

  it("escales Bmap = 3 jours à quai (pas 2)", () => {
    assert.equal(DEFAULT_PORT_DAYS.default, 3);
    assert.equal(portHoldHours("Ajaccio"), 72);
    assert.equal(portHoldHours("Cayenne"), 72);
    assert.equal(portHoldHours("Papeete"), 72);
    assert.equal(portHoldHours("Mata Utu"), 72);
    assert.equal(portHoldHours("Halifax"), 24);
    const { clock } = clockFor(DEFAULT_T0_ISO);
    assert.equal(clock.t0, DEFAULT_T0_ISO);
    const fdf = fdfMark(clock);
    assert.ok(fdf);
    assert.equal(fdf.holdHours, 72);
  });
});

describe("clockTickLabelsFromClock", () => {
  it("reprend nm et jours de l’horloge, pas un 2ᵉ barème", () => {
    const { clock } = clockFor(DEFAULT_T0_ISO);
    const ticks = clockTickLabelsFromClock(clock, "fr");
    assert.equal(ticks.length, 3);
    const last = lookupVoyageClock(clock, clock.vertices.at(-1).filmNm);
    assert.match(ticks[2].label, new RegExp(`j${Math.floor(last.seaHours / 24)}`));
    assert.match(ticks[0].label, /0 nm · j0/);
  });
});

describe("formatFilmClockLine", () => {
  it("compose nm · j · date UTC", () => {
    const line = formatFilmClockLine({
      sailNm: 4210,
      seaHours: 18 * 24 + 2,
      iso: "2026-07-03T14:00:00.000Z",
      lang: "fr",
    });
    assert.match(line, /4[\s ]?210 nm/);
    assert.match(line, /j18/);
    assert.match(line, /3 juil\. 14:00 UTC/);
  });
});
