import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { ALL_LAYER_CONFIG } from "./layers.js";

describe("ALL_LAYER_CONFIG", () => {
  it("remplace Science par les 8 cartes, sans pastille unique", () => {
    const keys = ALL_LAYER_CONFIG.map((c) => c.key);
    assert.deepEqual(keys, [
      "zee", "wpi", "balisage", "projects", "marinas",
      "capitaineries", "poe", "amp",
      "sextant", "argo", "odatis", "edmed", "csr",
      "bathymetry", "fonds", "cables",
      "climatology",
    ]);
    assert.equal(keys.includes("science"), false);
  });
});
