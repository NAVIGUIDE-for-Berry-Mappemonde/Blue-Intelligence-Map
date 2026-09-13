import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { haversineNm, summarizeRoute, featuresToSegments } from "./geo.js";

describe("summarizeRoute", () => {
  it("compte les segments et une distance > 0", () => {
    const { nm, segments } = summarizeRoute([
      { coords: [[-1.16, 46.15], [-16.15, 28.55]] },
      { coords: [[-16.15, 28.55], [-23.6, 15.1]] },
    ]);
    assert.equal(segments, 2);
    assert.ok(nm > 1000);
  });

  it("ignore les LineString trop courtes", () => {
    assert.deepEqual(summarizeRoute([{ coords: [[0, 0]] }]), { nm: 0, segments: 0 });
  });
});

describe("featuresToSegments", () => {
  it("extrait les LineString d'une FeatureCollection", () => {
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
