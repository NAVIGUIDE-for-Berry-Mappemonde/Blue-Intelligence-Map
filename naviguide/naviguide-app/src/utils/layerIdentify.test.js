import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { featureContains, kindFromLayer } from "./layerIdentify.js";

describe("kindFromLayer", () => {
  it("mappe les couches MapLibre", () => {
    assert.equal(kindFromLayer("bi-marinas-circle"), "marina");
    assert.equal(kindFromLayer("bi-amp-fill"), "amp");
  });
});

describe("featureContains", () => {
  const square = {
    geometry: {
      type: "Polygon",
      coordinates: [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
    },
  };
  it("détecte l'intérieur et l'extérieur", () => {
    assert.equal(featureContains(square, 1, 1), true);
    assert.equal(featureContains(square, 5, 5), false);
  });
});
