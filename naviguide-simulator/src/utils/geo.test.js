import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { haversineNm, summarizeRoute, featuresToSegments, splitAntimeridianCoords, unwrapLon, worldCopyCoords, worldCopyParts } from "./geo.js";

describe("summarizeRoute", () => {
  it("counts segments and a distance > 0", () => {
    const { nm, segments } = summarizeRoute([
      { coords: [[-1.16, 46.15], [-16.15, 28.55]] },
      { coords: [[-16.15, 28.55], [-23.6, 15.1]] },
    ]);
    assert.equal(segments, 2);
    assert.ok(nm > 1000);
  });

  it("ignores LineStrings that are too short", () => {
    assert.deepEqual(summarizeRoute([{ coords: [[0, 0]] }]), { nm: 0, segments: 0 });
  });
});

describe("antimeridian geo", () => {
  it("measures the short path on both sides of 180°", () => {
    const d = haversineNm(-15, 179.5, -15, -179.5);
    assert.ok(d < 80);
    assert.ok(d > 20);
    assert.equal(unwrapLon(179.5, -179.5), 180.5);
  });

  it("splits a polyline at 180°", () => {
    const parts = splitAntimeridianCoords([[179, 0], [179.9, 0], [-179.9, 0], [-179, 0]]);
    assert.equal(parts.length, 2);
  });

  it("copies a track at ±360° so Africa stays visible from the Pacific", () => {
    const copies = worldCopyCoords([[166, -22], [45, -13]]);
    assert.equal(copies.length, 3);
    assert.equal(copies[1][0][0], 526);
    assert.equal(copies[2][0][0], -194);
    assert.equal(worldCopyParts(copies.slice(0, 1)).length, 3);
  });
});

describe("featuresToSegments", () => {
  it("extracts LineStrings from a FeatureCollection", () => {
    const segs = featuresToSegments({
      type: "FeatureCollection",
      features: [
        { type: "Feature", geometry: { type: "Point", coordinates: [0, 0] } },
        { type: "Feature", geometry: { type: "LineString", coordinates: [[0, 0], [1, 1]] } },
      ],
    });
    assert.equal(segs.length, 1);
    assert.equal(haversineNm(0, 0, 1, 1) > 0, true);
  });
});
