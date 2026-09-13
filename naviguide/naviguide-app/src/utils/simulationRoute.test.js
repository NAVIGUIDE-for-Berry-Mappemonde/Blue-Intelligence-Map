import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  activeSimulationSegments,
  activeSimulationStops,
  buildSimTargets,
  simulationStartPos,
  stopsFromCustomRoute,
} from "./simulationRoute.js";

const customFc = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { name: "Point 1" },
      geometry: { type: "Point", coordinates: [-17.32, 48.15] },
    },
    {
      type: "Feature",
      properties: { name: "Point 2" },
      geometry: { type: "Point", coordinates: [-21.27, 31.97] },
    },
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [-17.32, 48.15],
          [-21.27, 31.97],
        ],
      },
    },
  ],
};

describe("stopsFromCustomRoute", () => {
  it("marque chaque waypoint comme escale", () => {
    const stops = stopsFromCustomRoute(customFc);
    assert.equal(stops.length, 2);
    assert.equal(stops[0].name, "Point 1");
    assert.equal(stops[0].flag, true);
    assert.equal(stops[1].lat, 31.97);
  });
});

describe("buildSimTargets", () => {
  it("part du premier point de la polyligne, pas de La Rochelle", () => {
    const segs = activeSimulationSegments(customFc, []);
    const targets = buildSimTargets(segs);
    assert.ok(targets.length >= 3);
    assert.equal(targets[0].lat, 48.15);
    assert.equal(targets[0].lon, -17.32);
    const last = targets[targets.length - 1];
    assert.equal(last.lat, 31.97);
    assert.equal(last.lon, -21.27);
    assert.ok(Math.abs(targets[0].lat - 46.1541) > 1);
  });

  it("retombe sur les stops si pas de LineString", () => {
    const stops = [{ lat: 10, lon: 20 }, { lat: 11, lon: 21 }];
    const targets = buildSimTargets([], stops);
    assert.deepEqual(targets, [
      { lat: 10, lon: 20 },
      { lat: 11, lon: 21 },
    ]);
  });
});

describe("activeSimulationStops / start", () => {
  it("utilise la route perso quand elle est affichée", () => {
    const berry = [{ name: "La Rochelle", lat: 46.15, lon: -1.16, flag: "fr" }];
    const stops = activeSimulationStops(customFc, berry);
    assert.equal(stops[0].name, "Point 1");
    const start = simulationStartPos(buildSimTargets(activeSimulationSegments(customFc, [])));
    assert.equal(start.lat, 48.15);
  });

  it("garde Berry sans route perso", () => {
    const berry = [{ name: "La Rochelle", lat: 46.15, lon: -1.16, flag: "fr" }];
    assert.equal(activeSimulationStops(null, berry)[0].name, "La Rochelle");
  });
});
