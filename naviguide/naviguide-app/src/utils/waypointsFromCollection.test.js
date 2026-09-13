import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { waypointsFromCollection } from "./waypointsFromCollection.js";

describe("waypointsFromCollection", () => {
  it("extrait les points dans l'ordre", () => {
    const wps = waypointsFromCollection({
      type: "FeatureCollection",
      features: [
        { type: "Feature", properties: { name: "A" }, geometry: { type: "Point", coordinates: [-1.15, 46.16] } },
        { type: "Feature", geometry: { type: "LineString", coordinates: [[0, 0], [1, 1]] } },
        { type: "Feature", properties: { name: "B" }, geometry: { type: "Point", coordinates: [-61.08, 14.6] } },
      ],
    });
    assert.equal(wps.length, 2);
    assert.equal(wps[0].name, "A");
    assert.equal(wps[0].lon, -1.15);
    assert.equal(wps[1].name, "B");
    assert.equal(wps[1].lat, 14.6);
  });

  it("retombe sur les extrémités des LineString", () => {
    const wps = waypointsFromCollection({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "LineString", coordinates: [[-1.15, 46.16], [-5, 48.4]] },
        },
      ],
    });
    assert.equal(wps.length, 2);
    assert.equal(wps[0].name, "Départ");
    assert.equal(wps[1].lon, -5);
  });

  it("ignore les collections vides", () => {
    assert.deepEqual(waypointsFromCollection(null), []);
    assert.deepEqual(waypointsFromCollection({ features: [] }), []);
  });
});
