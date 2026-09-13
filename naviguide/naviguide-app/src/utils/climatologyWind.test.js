import test from "node:test";
import assert from "node:assert/strict";
import { boatSpeedFromClimatology, zoneWindAt } from "./climatologyWind.js";

test("alizés Atlantique : mars plus fort que juillet, ETA qui bouge", () => {
  const mar = boatSpeedFromClimatology(15, -25, 3);
  const jul = boatSpeedFromClimatology(15, -25, 7);
  assert.equal(mar.kind, "climatology");
  assert.equal(mar.source, "zone_fallback");
  assert.ok(mar.windKnots > jul.windKnots);
  const etaMar = 700 / mar.speedKnots;
  const etaJul = 700 / jul.speedKnots;
  assert.ok(etaMar !== etaJul);
});

test("MOST_LIKELY zone ≠ unique 18 kn seulement hors saison", () => {
  const winter = zoneWindAt(15, -25, 1);
  const summer = zoneWindAt(15, -25, 8);
  assert.equal(winter.dirFromDeg, 50);
  assert.equal(winter.speedKnots, 18);
  assert.equal(summer.speedKnots, 12);
});
