import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  computeMarkerOffsets,
  capOffset,
  hasFlag,
  MAX_OFFSET,
  FLAG_W,
  FLAG_H,
  rectHitsRoute,
} from "./markerOffsets.js";

const identityProject = (lon, lat) => ({ x: lon, y: lat });

describe("hasFlag / capOffset", () => {
  it("traite une chaîne vide comme point intermédiaire", () => {
    assert.equal(hasFlag({ flag: "" }), false);
    assert.equal(hasFlag({ flag: "/flags/fr.png" }), true);
  });

  it("plafonne un offset trop long", () => {
    const [ox, oy] = capOffset(0, -400);
    assert.ok(Math.hypot(ox, oy) <= MAX_OFFSET + 1e-6);
    assert.equal(ox, 0);
    assert.ok(oy < 0);
  });
});

describe("computeMarkerOffsets", () => {
  it("laisse les points intermédiaires à [0, 0]", () => {
    const points = [
      { lon: 0, lat: 0, flag: "" },
      { lon: 10, lat: 10, flag: "" },
    ];
    const offsets = computeMarkerOffsets(points, identityProject);
    assert.deepEqual(offsets[0], [0, 0]);
    assert.deepEqual(offsets[1], [0, 0]);
  });

  it("ne laisse jamais un drapeau au-delà de MAX_OFFSET", () => {
    const points = [];
    for (let i = 0; i < 12; i++) {
      points.push({ lon: 100 + i * 2, lat: 100 + i * 2, flag: "x" });
    }
    const offsets = computeMarkerOffsets(points, identityProject);
    for (const [ox, oy] of offsets) {
      assert.ok(Math.hypot(ox, oy) <= MAX_OFFSET + 1e-6, `${ox},${oy}`);
    }
  });

  it("écarte deux drapeaux trop proches", () => {
    const points = [
      { lon: 50, lat: 50, flag: "a" },
      { lon: 52, lat: 50, flag: "b" },
    ];
    const offsets = computeMarkerOffsets(points, identityProject);
    const ax = 50 + offsets[0][0];
    const ay = 50 + offsets[0][1];
    const bx = 52 + offsets[1][0];
    const by = 50 + offsets[1][1];
    const dist = Math.hypot(bx - ax, by - ay);
    assert.ok(dist >= 20, `drapeaux trop proches: ${dist}`);
  });

  it("évite de poser le rectangle du drapeau sur la route", () => {
    const points = [{ lon: 0, lat: 0, flag: "a" }];
    // Route horizontale qui passe par l'ancre — un offset (0,0) recouperait
    const routeSegs = [{ ax: -80, ay: 0, bx: 80, by: 0 }];
    const [ox, oy] = computeMarkerOffsets(points, identityProject, routeSegs)[0];
    const rect = {
      x: ox - FLAG_W / 2,
      y: oy - FLAG_H,
      w: FLAG_W,
      h: FLAG_H,
    };
    assert.equal(rectHitsRoute(rect, routeSegs, 2), false);
  });
});
