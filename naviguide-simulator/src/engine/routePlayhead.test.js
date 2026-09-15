import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  atlanticSpanNm,
  chapterAtNm,
  filmLegContext,
  flattenRoute,
  interpolateAtNm,
  isNamedEscale,
  mapEscalesOnRoute,
  nearestNm,
  nextEscaleNm,
  playheadOnPlay,
  prevEscaleNm,
} from "./routePlayhead.js";

const SEGMENTS = [
  { nonMaritime: true, coords: [[0, 0], [0, 1]] },
  { nonMaritime: false, coords: [[0, 1], [1, 1], [2, 1]] },
];

describe("flattenRoute", () => {
  it("starts at the first vertex and accumulates nm", () => {
    const flat = flattenRoute(SEGMENTS);
    assert.equal(flat.points[0].lat, 0);
    assert.equal(flat.points[0].lon, 0);
    assert.ok(flat.totalNm > 60);
    assert.equal(flat.points[0].nonMaritime, true);
  });
});

describe("interpolateAtNm / nearestNm", () => {
  it("returns to the start at 0 and to the arrival at the total", () => {
    const flat = flattenRoute(SEGMENTS);
    const a = interpolateAtNm(flat, 0);
    const b = interpolateAtNm(flat, flat.totalNm);
    assert.equal(a.lat, 0);
    assert.ok(Math.abs(b.lon - 2) < 1e-6);
    const mid = interpolateAtNm(flat, flat.totalNm / 2);
    const back = nearestNm(flat, mid.lat, mid.lon);
    assert.ok(Math.abs(back - flat.totalNm / 2) < 2);
  });
});

describe("escales", () => {
  it("ignores unflagged points and advances in order", () => {
    assert.equal(isNamedEscale({ flag: "" }), false);
    assert.equal(isNamedEscale({ flag: "/x.png" }), true);
    const flat = flattenRoute(SEGMENTS);
    const marks = mapEscalesOnRoute([
      { name: "A", lat: 0, lon: 0, flag: "f" },
      { name: "skip", lat: 0.5, lon: 0, flag: "" },
      { name: "B", lat: 1, lon: 2, flag: "f" },
    ], flat);
    assert.equal(marks.length, 2);
    assert.equal(marks[0].name, "A");
    assert.ok(marks[1].nm > marks[0].nm);
    const ch = chapterAtNm(marks, marks[0].nm + 1);
    assert.equal(ch.from.name, "A");
    assert.equal(ch.to.name, "B");
    assert.equal(nextEscaleNm(marks, 0), marks[1].nm);
    assert.equal(prevEscaleNm(marks, marks[1].nm), marks[0].nm);
    assert.equal(nextEscaleNm(marks, marks[1].nm), marks[1].nm);
  });
});

describe("atlanticSpanNm", () => {
  it("takes La Rochelle → Fort-de-France", () => {
    const span = atlanticSpanNm([
      { name: "La Rochelle", nm: 100 },
      { name: "Ajaccio (Corse)", nm: 2000 },
      { name: "Fort-de-France (Martinique)", nm: 7100 },
    ], 39000);
    assert.equal(span, 7000);
  });
});

describe("Guiana → SPM air hop", () => {
  it("does not count the Cayenne→Halifax plane in nm", () => {
    const flat = flattenRoute([
      { coords: [[-52.3533, 4.9333], [-52.35, 4.94]] },
      { coords: [[-63.5652, 44.6488], [-56.1628, 46.7761]] },
    ]);
    assert.ok(flat.totalNm < 700);
    assert.ok(flat.totalNm > 200);
    assert.ok(flat.points.some((p) => p.jump));
    assert.ok(flat.totalFilmNm > flat.totalNm);
    assert.equal(flat.episodes.length, 0);
    const cayenneEnd = flat.points.find((p) => p.jump);
    const here = interpolateAtNm(flat, cayenneEnd.cumNm);
    assert.ok(Math.abs(here.lat - 44.65) < 0.4);
    assert.equal(here.jump, false);
  });
});

describe("antimeridian", () => {
  it("does not send the boat to meridian 0°", () => {
    const flat = flattenRoute([
      { coords: [[179.2, -15], [179.8, -15], [-179.8, -15], [-179.2, -15]] },
    ]);
    const mid = interpolateAtNm(flat, flat.totalNm / 2);
    const lon = ((mid.lon + 540) % 360) - 180;
    assert.ok(Math.abs(lon) > 170, `lon interpolé ${mid.lon}`);
    assert.ok(flat.totalNm < 120);
  });
});

describe("filmLegContext", () => {
  it("keeps full names and computes ETA with boat speed", () => {
    const marks = [
      { name: "Saint-Maur (Berry, Indre)", nm: 0 },
      { name: "La Rochelle", nm: 200 },
    ];
    const hud = filmLegContext({
      marks,
      nm: 50,
      sample: { lon: 1, lat: 46, bearing: 270 },
      totalNm: 200,
      boatKnots: 10,
    });
    assert.equal(hud.fromStop, "Saint-Maur (Berry, Indre)");
    assert.equal(hud.toStop, "La Rochelle");
    assert.equal(hud.nmCovered, 50);
    assert.equal(hud.nmRemainingToStop, 150);
    assert.equal(hud.etaHours, 15);
    assert.equal(hud.finished, false);
    assert.deepEqual(hud.snappedPosition, [1, 46]);
  });
});

describe("playheadOnPlay", () => {
  it("repart de 0 si on est à la fin", () => {
    assert.equal(playheadOnPlay(12000, 12000), 0);
    assert.equal(playheadOnPlay(11999.999999, 12000), 0);
    assert.equal(playheadOnPlay(400, 12000), 400);
    assert.equal(playheadOnPlay(0, 12000), 0);
  });
});
