import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { isRouteReady } from "./routeReady.js";

describe("isRouteReady", () => {
  it("false tant que le total est inconnu ou incomplet", () => {
    assert.equal(isRouteReady(null), false);
    assert.equal(isRouteReady({ done: 0, total: 0 }), false);
    assert.equal(isRouteReady({ done: 3, total: 12 }), false);
  });

  it("true quand toutes les jambes sont là", () => {
    assert.equal(isRouteReady({ done: 12, total: 12 }), true);
    assert.equal(isRouteReady({ done: 13, total: 12 }), true);
  });
});
