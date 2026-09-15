import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { corridorBboxOk, corridorForBoat, pointInBbox } from "./gribCorridor.js";

describe("couloir GRIB", () => {
  it("accepte un rectangle bateau, refuse un globe", () => {
    assert.equal(corridorBboxOk([10, 16, -65, -58]), true);
    assert.equal(corridorBboxOk([-80, 80, -180, 180]), false);
    assert.equal(corridorBboxOk(null), false);
  });

  it("recentre sur le bateau si le bbox serveur est ailleurs", () => {
    const server = [-3, 3, -103, -96];
    assert.equal(pointInBbox(server, 0.1, -99), true);
    assert.equal(pointInBbox(server, -22, 166), false);
    const local = corridorForBoat(server, -22.3, 166.4);
    assert.ok(local[0] < -22.3 && local[1] > -22.3);
    assert.ok(Math.abs(local[2] - 166.4) < 4);
  });
});
