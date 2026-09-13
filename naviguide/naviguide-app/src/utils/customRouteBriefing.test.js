import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildLocalCustomBriefing } from "./customRouteBriefing.js";

const laRochelleBrest = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { name: "La Teste" },
      geometry: { type: "Point", coordinates: [-1.14, 44.63] },
    },
    {
      type: "Feature",
      properties: { name: "Ouessant" },
      geometry: { type: "Point", coordinates: [-5.1, 48.46] },
    },
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [-1.14, 44.63],
          [-5.1, 48.46],
        ],
      },
    },
  ],
};

describe("buildLocalCustomBriefing", () => {
  it("refuse une collection trop courte", () => {
    assert.equal(
      buildLocalCustomBriefing({
        type: "FeatureCollection",
        features: [{ type: "Feature", geometry: { type: "Point", coordinates: [-1, 46] } }],
      }),
      null,
    );
  });

  it("décrit la route dessinée, pas Berry, avec executive_briefing", () => {
    const plan = buildLocalCustomBriefing(laRochelleBrest, "fr");
    assert.ok(plan.executive_briefing.includes("Route personnalisée"));
    assert.ok(plan.executive_briefing.includes("tracée à la main"));
    assert.ok(plan.executive_briefing.includes("La Teste"));
    assert.ok(plan.executive_briefing.includes("Ouessant"));
    assert.ok(plan.executive_briefing.includes("44.63°N"));
    assert.ok(!/papeete|saint-maur|halifax/i.test(plan.executive_briefing));
    assert.ok(!/la rochelle/i.test(plan.executive_briefing));
    assert.equal(plan.localFallback, true);
    assert.match(plan.executive_briefing, /\d+ NM/);
  });

  it("version anglaise", () => {
    const plan = buildLocalCustomBriefing(laRochelleBrest, "en");
    assert.ok(plan.executive_briefing.includes("Custom route"));
    assert.ok(plan.executive_briefing.includes("La Teste"));
  });
});
