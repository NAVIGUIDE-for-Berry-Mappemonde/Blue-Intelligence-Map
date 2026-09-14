import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { filterScienceFeatures, scienceSourceOf } from "./scienceSource.js";

describe("scienceSourceOf", () => {
  it("lit source, sinon kind argo/csr", () => {
    assert.equal(scienceSourceOf({ source: "sextant" }), "sextant");
    assert.equal(scienceSourceOf({ kind: "argo_float" }), "argo");
    assert.equal(scienceSourceOf({ kind: "cruise" }), "csr");
    assert.equal(scienceSourceOf({}), "");
  });
});

describe("filterScienceFeatures", () => {
  it("garde une source à la fois", () => {
    const fc = {
      type: "FeatureCollection",
      features: [
        { properties: { source: "sextant" }, geometry: { type: "Point", coordinates: [0, 0] } },
        { properties: { kind: "argo_float" }, geometry: { type: "Point", coordinates: [1, 1] } },
        { properties: { source: "csr", kind: "cruise" }, geometry: { type: "LineString", coordinates: [[0, 0], [1, 1]] } },
      ],
    };
    assert.equal(filterScienceFeatures(fc, "sextant").features.length, 1);
    assert.equal(filterScienceFeatures(fc, "argo").features.length, 1);
    assert.equal(filterScienceFeatures(fc, "csr").features[0].geometry.type, "LineString");
    assert.equal(filterScienceFeatures(fc, "odatis").features.length, 0);
  });
});
